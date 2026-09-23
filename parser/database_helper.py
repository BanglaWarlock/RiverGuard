"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

Every database operation, one small function each.

Handlers never touch pymongo directly, they call these. A future dev
changing the database (schema, provider, queries) edits ONLY this file.
All functions read the database handle from state.state, which main.py
guarantees is set before any message can arrive.
"""

import datetime
from pymongo import ReturnDocument
import state

def _db():
    return state.state["db"]

def utcnow():
    return datetime.datetime.utcnow()


# inserts
"""One compact time-series row: who, what param, value, when."""
def insert_telemetry(node_id, village, param, value, when):
    _db().telemetry.insert_one({
        "node_id": node_id, "village_id": village,
        "param": param, "value": value, "timestamp": when,
    })

"""One compact alert record."""
def insert_alert(node_id, village, alert_type, value, when):
    _db().alerts.insert_one({
        "node_id": node_id, "village_id": village,
        "type": alert_type, "value": value, "timestamp": when,
    })

"""One lifecycle event: what happened, who, which village, when."""
def log_event(event_type, village, node_id=None, data=None):
    _db().events.insert_one({
        "event_type": event_type, "village_id": village, "node_id": node_id,
        "data": data or {}, "timestamp": utcnow(),
    })

# nodes
"""
Create-or-update a river node document (auto-registration).

Every river-node handler goes through here, so a node doc exists
after ANY message about it. Fields the message didn't carry stay
at their creation defaults (null) until something provides them.

Returns the PREVIOUS document, or None if the node was just created.
"""
def upsert_river_node(village, node_id, status, set_updates=None):
    now = utcnow()

    set_doc = {"status": status, "last_seen": now}
    set_doc.update(set_updates or {})

    on_insert = {
        "village_id": village,
        "parent_id": None,
        "depth": None,
        "coordinates": None,
        "install_coordinates": None,
        "alert_counts": {},
        "created_at": now,
    }
    # $setOnInsert can't overlap $set paths - drop defaults the caller provides
    for key in list(on_insert):
        if key in set_doc:
            del on_insert[key]

    return _db().river_nodes.find_one_and_update(
        {"node_id": node_id, "village_id": village},
        {"$set": set_doc, "$setOnInsert": on_insert},
        upsert=True,
        return_document=ReturnDocument.BEFORE,
    )

"""Tally the alert on the node doc and the village doc."""
def increment_alert_counts(village, node_id, alert_type):
    _db().river_nodes.update_one(
        {"node_id": node_id, "village_id": village},
        {"$inc": {f"alert_counts.{alert_type}": 1}},
    )
    _db().villages.update_one(
        {"_id": village},
        {"$inc": {f"alerts_by_type.{alert_type}": 1},
         "$setOnInsert": {"village_id": village, "master_id": None,
                          "is_online": False, "topology": {}}},
        upsert=True,
    )

"""
Bookkeeping for a river node status change (including creation):
village counters, global counters, one event.
Callers only invoke this when the status actually changed.
"""
def apply_node_status_change(village, node_id, online, source, created=False):

    now = utcnow()

    if created:
        village_inc = {"total_river_nodes": 1}
        global_inc = {}
        if online:
            village_inc["river_nodes_online"] = 1
            global_inc["river_nodes_online"] = 1
        else:
            village_inc["river_nodes_offline"] = 1
            global_inc["river_nodes_offline"] = 1
    else:
        village_inc = {
            "river_nodes_online": 1 if online else -1,
            "river_nodes_offline": -1 if online else 1,
        }
        global_inc = dict(village_inc)

    _db().villages.update_one(
        {"_id": village},
        {"$inc": village_inc, "$set": {"last_seen": now},
         "$setOnInsert": {"village_id": village, "master_id": None,
                          "is_online": False, "topology": {}, "alerts_by_type": {}}},
        upsert=True,
    )
    _db().global_stats.update_one(
        {"_id": "global"},
        {"$inc": global_inc, "$set": {"updated_at": now}},
        upsert=True,
    )
    log_event("node_online" if online else "node_offline", village, node_id,
              {"source": source, "created": created})

"""Hops from the master (master = 0, first hop = 1). Walks parent links
upward; stops at the master (masters are not in river_nodes)."""
def compute_depth(village, parent_id):

    depth = 0
    current = parent_id
    for _ in range(20):   # safety cap against bad/cyclic parent links
        if not current:
            break
        depth += 1
        node = _db().river_nodes.find_one(
            {"node_id": current, "village_id": village}, {"parent_id": 1})
        if node is None:
            break   # reached the master
        current = node.get("parent_id")
    return depth


# masters
"""Create-or-update the master's record. Returns its PREVIOUS online state."""
def upsert_master_node(village, node_id, online, when):
    previous = _db().master_nodes.find_one_and_update(
        {"node_id": node_id},
        {"$set": {"village_id": village,
                  "status": "online" if online else "offline",
                  "last_seen": when},
         "$setOnInsert": {"created_at": when}},
        upsert=True,
        return_document=ReturnDocument.BEFORE,
    )
    return bool(previous and previous.get("status") == "online")

"""Point the village doc at its master and set its online flag."""
def set_village_master(village, node_id, online, when):
    _db().villages.update_one(
        {"_id": village},
        {"$set": {"master_id": node_id, "is_online": online, "last_seen": when},
         "$setOnInsert": {"village_id": village, "topology": {}, "alerts_by_type": {}}},
        upsert=True,
    )

"""Global counters + event - callers only call on real transitions."""
def apply_master_status_change(village, node_id, online, when):
    _db().global_stats.update_one(
        {"_id": "global"},
        {"$inc": {"masters_online": 1 if online else -1,
                  "masters_offline": -1 if online else 1},
         "$set": {"updated_at": when}},
        upsert=True,
    )
    log_event("master_online" if online else "master_offline", village, node_id)


# topology
"""
Rebuild the village mesh tree from river_nodes parent links, stored
on the village doc: {master_id: {child: {grandchild: {}}}}
parent_id links are the truth; this tree is a cached view for the
frontend. Orphans (unreachable from master) are excluded.
"""
def rebuild_topology(village):

    village_doc = _db().villages.find_one({"_id": village}) or {}
    master_id = village_doc.get("master_id") or f"{village}-M01"

    children = {}
    for node in _db().river_nodes.find({"village_id": village},
                                       {"node_id": 1, "parent_id": 1}):
        children.setdefault(node.get("parent_id"), []).append(node["node_id"])

    def build(node_id):
        return {child: build(child) for child in children.get(node_id, [])}

    tree = {master_id: build(master_id)}
    _db().villages.update_one(
        {"_id": village},
        {"$set": {"topology": tree},
         "$setOnInsert": {"village_id": village, "alerts_by_type": {}}},
        upsert=True,
    )
    return tree

"""Store the master's authoritative tree on the village doc."""
def store_village_topology(village, tree, root, when):
    update_set = {"topology": tree, "last_seen": when}
    if root:
        update_set["master_id"] = root
    _db().villages.update_one(
        {"_id": village},
        {"$set": update_set,
         "$setOnInsert": {"village_id": village, "alerts_by_type": {}}},
        upsert=True,
    )

"""
Align river_nodes with the master's tree: update parent_id/depth of
known nodes, auto-create unknown ones. Returns how many were created.
"""
def reconcile_topology(village, tree, root):

    parent_map = {}
    depth_map = {}

    def walk(parent_id, subtree, depth):
        for child, sub in (subtree or {}).items():
            parent_map[child] = parent_id
            depth_map[child] = depth
            walk(child, sub, depth + 1)

    walk(root, tree[root], 1)

    created = 0
    for node_id, parent_id in parent_map.items():
        exists = _db().river_nodes.find_one(
            {"node_id": node_id, "village_id": village}, {"_id": 1})
        if exists:
            _db().river_nodes.update_one(
                {"node_id": node_id, "village_id": village},
                {"$set": {"parent_id": parent_id, "depth": depth_map[node_id]}},
            )
        else:
            upsert_river_node(village, node_id, "online",
                              set_updates={"parent_id": parent_id,
                                           "depth": depth_map[node_id]})
            apply_node_status_change(village, node_id, online=True,
                                     source="topology", created=True)
            created += 1
    return created