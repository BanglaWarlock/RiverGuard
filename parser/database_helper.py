"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

Every database operation, one small function each.
Handlers never touch pymongo directly - a future dev changing the
database edits ONLY this file. Handles come from state.state.
Time saved at utc value.
"""

import datetime
import state

def _db():
    return state.state["db"]

def utcnow():
    return datetime.datetime.utcnow()

def upsert_mesh_node_from_telemetry(node_id, payload, now):
    """Latest snapshot from a telemetry message."""
    _db().mesh_nodes.update_one(
        {"node_id": node_id},
        {"$set": {
            "last_seen": now,
            "telemetry_seq": payload.get("sequence"),
            "uptime_minute": payload.get("uptime_minute"),
            "sf": payload.get("sf"),
            "tx_packets": payload.get("tx_packets"),
            "rx_packets": payload.get("rx_packets"),
            "tx_bytes": payload.get("tx_bytes"),
            "rx_bytes": payload.get("rx_bytes"),
        },
         "$setOnInsert": {"node_id": node_id, "first_seen": now}},
        upsert=True)


def upsert_mesh_node_from_route(node_id, payload, now):
    """Latest route-derived snapshot. first_hop_rssi/snr are from the
    first route entry with a non-null reading - stored as reported,
    no interpretation (which entry is 'the' link is a hardware-side
    question; the website displays what's sent)."""
    routes = payload.get("r", [])
    first_hop = next((r for r in routes if r.get("ri") is not None), None)
    _db().mesh_nodes.update_one(
        {"node_id": node_id},
        {"$set": {
            "last_seen": now,
            "topology_seq": payload.get("s"),
            "link_count": len(routes),
            "first_hop_rssi": first_hop.get("ri") if first_hop else None,
            "first_hop_snr": first_hop.get("sn") if first_hop else None,
        },
         "$setOnInsert": {"node_id": node_id, "first_seen": now}},
        upsert=True)

def insert_telemetry(node_id, payload, now):
    """One telemetry message, verbatim."""
    _db().telemetry.insert_one({
        "node_id": node_id,
        "payload": payload,
        "timestamp": now,
    })
    
# raw mesh history 
def insert_route_report(node_id, payload, now):
    _db().route_reports.insert_one({
        "node_id": node_id,
        "payload": payload,
        "timestamp": now,
    })

def insert_blacklist(payload, now):
    """Store one policy version AND update the active-policy document."""
    _db().blacklists.insert_one({
        "v": payload.get("v"),
        "sequence": payload.get("sequence"),
        "edges": payload.get("edges", []),
        "timestamp": now,
    })
    _db().current_blacklist.update_one(
        {"_id": "active"},
        {"$set": {
            "v": payload.get("v"),
            "sequence": payload.get("sequence"),
            "edges": payload.get("edges", []),
            "received": now,
        }},
        upsert=True)

def blacklist_exists(payload):
    """True if this exact version is already stored (retained
    re-deliveries of the same v + sequence are recognized)."""
    return _db().blacklists.find_one({
        "v": payload.get("v"),
        "sequence": payload.get("sequence"),
    }) is not None

def get_current_blacklist():
    """The active policy, or None if none has been published."""
    return _db().current_blacklist.find_one({"_id": "active"})
    
    