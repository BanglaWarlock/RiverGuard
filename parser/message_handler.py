"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

One handle_* function per message type.

Each handler: validate payload -> 
database writes (via database_helper) ->
notify the API (via redis_helper).

"""

import datetime
import json

import state
import database_helper
import redis_helper

# Per-parameter telemetry: riverguard/{village}/{param}/{node_id}
# Maps MQTT msg_type -> Redis channel.
TELEMETRY_PARAMS = {
    "battery": "riverguard:battery",
    "water":   "riverguard:water",
    "gps":     "riverguard:gps",
    "signal":  "riverguard:signal",
}


def utcnow():
    return datetime.datetime.utcnow()


"""
Per-parameter telemetry update (battery/water/gps/signal).

data is a bare JSON number (battery: 13.2, water: 7) or an object.
Any telemetry is proof of life: node marked online, latest value
stored, one compact telemetry row, one Redis publish.

Water convention: value is the FLOAT BITS (1ft=0b001, 2ft=0b011,
3ft=0b111); water_level is derived and stored alongside.
"""
def handle_telemetry(village, node_id, param, data):
    now = utcnow()

    # 1. Validate + normalize the payload into node fields
    if param == "battery":
        v = data.get("value") if isinstance(data, dict) else data
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            # tood : uncomment
            # print(f"  - WARNING: battery needs a number, got {data!r}")
            return
        node_fields, value = {"bat": v}, v

    elif param == "water":
        bits = data.get("float_bits") if isinstance(data, dict) else data
        try:
            bits = int(bits or 0)
        except (TypeError, ValueError):
            bits = -1
        if not 0 <= bits <= 7:
            # tood : uncomment
            # print(f"  - WARNING: water needs float_bits 0-7, got {data!r}")
            return
        node_fields = {"float_bits": bits, "water_level": bits.bit_length()}
        value = bits

    elif param == "gps":
        if not isinstance(data, dict) or "lat" not in data or "lng" not in data:
            # tood : uncomment
            # print(f"  - WARNING: gps needs {{lat, lng, gps_fix?}}, got {data!r}")
            return
        node_fields = {
            "coordinates": {"lat": data.get("lat"), "lng": data.get("lng")},
            "gps_fix": data.get("gps_fix"),
        }
        value = data

    elif param == "signal":
        if not isinstance(data, dict):
                # tood : uncomment
            # print(f"  - WARNING: signal needs {{rssi, snr}}, got {data!r}")
            return
        node_fields = {"rssi": data.get("rssi"), "snr": data.get("snr")}
        value = data

    print(f"[{param}] {node_id} from {village} -> {value}")

    # 2. Compact time-series row: who, what param, value, when
    database_helper.insert_telemetry(node_id, village, param, value, now)

    # 3. Latest value on the node doc (auto-registers unknown nodes)
    previous = database_helper.upsert_river_node(village, node_id, "online",
                                           set_updates=node_fields)
    if previous is None:
        # tood : uncomment
        # print("  - Unknown node, auto-registered (parent null until it announces)")
        database_helper.apply_node_status_change(village, node_id, online=True,
                                           source=param, created=True)
    elif previous.get("status") != "online":
            # tood : uncomment
        # print(f"  - Node was '{previous.get('status')}' -> ONLINE (revived by {param})")
        database_helper.apply_node_status_change(village, node_id, online=True, source=param)

    # 4. Notify the API - data merges straight into the node's state
    redis_helper.publish(TELEMETRY_PARAMS[param], {
        "village": village, "node_id": node_id,
        "data": node_fields, "ts": now.isoformat(),
    })


"""Alert message. Compact: type + value + who + which village + when."""
def handle_alert(village, node_id, payload):
    now = utcnow()
    alert_type = payload.get("type", "unknown")
    value = payload.get("value")

    # tood : uncomment
    # print(f"[ALERT] {node_id} from {village}")
    # print(f"  - Type: {alert_type}, value: {value}")

    database_helper.insert_alert(node_id, village, alert_type, value, now)

    # An alert is proof of life -> status online + alert tallies
    previous = database_helper.upsert_river_node(village, node_id, "online")
    database_helper.increment_alert_counts(village, node_id, alert_type)

    if previous is None:
        # tood : uncomment
        # print("  - Unknown node, auto-registered (parent null until it announces)")
        database_helper.apply_node_status_change(village, node_id, online=True,
                                           source="alert", created=True)
    elif previous.get("status") != "online":
        database_helper.apply_node_status_change(village, node_id, online=True, source="alert")

    redis_helper.publish("riverguard:alert", {
        "village": village, "node_id": node_id,
        "data": {"type": alert_type, "value": value}, "ts": now.isoformat(),
    })


"""Node deployment/registration (GPS install position + parent)."""
def handle_announce(village, node_id, payload):
    now = utcnow()
    parent = payload.get("parent")
    lat, lng = payload.get("lat"), payload.get("lng")
    depth = database_helper.compute_depth(village, parent) if parent else None

    # tood : uncomment
    # print(f"[announce] {node_id} from {village}")
    # print(f"  - Parent: {parent} (depth: {depth})")
    # print(f"  - Install position: {lat}, {lng}")

    set_updates = {
        "parent_id": parent,
        "depth": depth,
        "install_coordinates": {"lat": lat, "lng": lng},
        "rssi": payload.get("rssi"),
        "snr": payload.get("snr"),
    }
    if lat is not None:
        set_updates["coordinates"] = {"lat": lat, "lng": lng}

    previous = database_helper.upsert_river_node(village, node_id, "online",
                                           set_updates=set_updates)
    if previous is None:
        print(f"  - NEW node registered for village {village}")
        database_helper.apply_node_status_change(village, node_id, online=True,
                                           source="announce", created=True)
        database_helper.log_event("node_announce", village, node_id,
                            {"parent": parent, "depth": depth})
    elif previous.get("status") != "online":
            # tood : uncomment
        # print("  - Existing node re-announced (was offline, revived)")
        database_helper.apply_node_status_change(village, node_id, online=True, source="announce")
    else:
        print(f"  - Existing node re-announced (parent -> {parent}, depth -> {depth})")

    tree = database_helper.rebuild_topology(village)
        # tood : uncomment
    # print(f"  - Topology: {json.dumps(tree)}")

    redis_helper.publish("riverguard:node_status", {
        "village": village, "node_id": node_id,
        "data": {"event": "announce", "parent": parent, "depth": depth,
                 "lat": lat, "lng": lng, "topology": tree},
        "ts": now.isoformat(),
    })


"""Node online/offline status."""
def handle_node_status(village, node_id, payload):
    
    online = bool(payload.get("online", False))
    status = "online" if online else "offline"

    # tood : uncomment

    # print(f"[status] {node_id} from {village} -> {status.upper()}")

    previous = database_helper.upsert_river_node(village, node_id, status)
    if previous is None:
            # tood : uncomment
        # print("  - Unknown node, auto-registered (parent null until it announces)")
        database_helper.apply_node_status_change(village, node_id, online=online,
                                           source="status_message", created=True)
    elif previous.get("status") != status:
        database_helper.apply_node_status_change(village, node_id, online=online,
                                           source="status_message")

    redis_helper.publish("riverguard:node_status", {
        "village": village, "node_id": node_id,
        "data": {"online": online}, "ts": utcnow().isoformat(),
    })

"""Master node online/offline. The village is online iff its master is."""
def handle_master_status(village, payload):
    now = utcnow()
    online = bool(payload.get("online", False))
    node_id = payload.get("node_id") or f"{village}-M01"

    # tood : uncomment
    # print(f"[master] {village} -> {'ONLINE' if online else 'OFFLINE'}")
    # print(f"  - Master node: {node_id}")

    was_online = database_helper.upsert_master_node(village, node_id, online, now)
    database_helper.set_village_master(village, node_id, online, now)

    # Counters + event only on transitions (a first-ever "offline" message
    # is NOT a transition: nothing was lost)
    if was_online != online:
        database_helper.apply_master_status_change(village, node_id, online, now)

    redis_helper.publish("riverguard:village_status", {
        "village": village, "node_id": node_id,
        "data": {"online": online, "master_id": node_id}, "ts": now.isoformat(),
    })


"""
Full mesh topology broadcast from the master.
"""
def handle_topology(village, payload):
    now = utcnow()
    # tood : uncomment
    # print(f"[topology] {village}")
    # print(f"  - Tree: {json.dumps(payload)}")

    root = next(iter(payload), None)
    database_helper.store_village_topology(village, payload, root, now)

    if root:
        created = database_helper.reconcile_topology(village, payload, root)
    # tood : uncomment
        
        # print(f"  - Reconciled, auto-registered {created} new node(s)")

    redis_helper.publish("riverguard:topology", {
        "village": village, "node_id": None,
        "data": {"topology": payload}, "ts": now.isoformat(),
    })