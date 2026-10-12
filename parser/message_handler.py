"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

One handle_* function per message type.
Each handler: validate -> database writes (database_helper) ->
notify the API (redis_helper).
"""

import datetime
import database_helper as db_helper
import redis_helper
import logger

def utcnow():
    return datetime.datetime.utcnow()

# Mesh messages (hardware network layer, from the LoRa mesh team)

# mesh/{node}/telemetry - node health report
def handle_mesh_telemetry(node_id, payload):
    now = utcnow()
    try:
        db_helper.insert_telemetry(node_id, payload, now)
        db_helper.upsert_mesh_node_from_telemetry(node_id, payload, now)
        redis_helper.publish("riverguard:mesh", {
            "node_id": node_id,
            "data": {"event": "telemetry", "payload": payload},
            "ts": now.isoformat(),
        })
    except Exception as e:
        logger.log_error("handle_mesh_telemetry", e)
        
# mesh/route/{node} - one node's routing table (stored raw)
def handle_mesh_route(node_id, payload):
    now = utcnow()
    try:
        db_helper.insert_route_report(node_id, payload, now)
        db_helper.upsert_mesh_node_from_route(node_id, payload, now)

        redis_helper.publish("riverguard:mesh", {
            "node_id": node_id,
            "data": {"event": "route", "s": payload.get("s")},
            "ts": now.isoformat(),
        })
    except Exception as e:
        logger.log_error("handle_mesh_route", e)
    
# mesh/control/blacklist - link policy (retained, QoS 0)
def handle_mesh_blacklist(payload):
    now = utcnow()
    try:
        if db_helper.blacklist_exists(payload):
            return   # retained re-delivery of the version we already stored

        db_helper.insert_blacklist(payload, now)

        redis_helper.publish("riverguard:mesh", {
            "node_id": None,
            "data": {"event": "blacklist", "payload": payload},
            "ts": now.isoformat(),
        })
    except Exception as e:
        logger.log_error("handle_mesh_blacklist", e)
        