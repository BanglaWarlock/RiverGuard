"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

Connect to (and disconnect from) the three external systems:
MongoDB, the MQTT broker, and Redis.

The MQTT callbacks live in mqtt_handlers.py.
"""

import paho.mqtt.client as mqtt
from pymongo import MongoClient
import redis

import config
import state
import mqtt_handlers
import logger

# MongoDB
def setup_database():
    """Connect, create indexes. Returns True/False."""
    try:
        client = MongoClient(config.DB_URI)
        db = client[config.DB_NAME]
        
        # mesh_nodes - current state
        db.mesh_nodes.create_index([("node_id", 1)], unique=True)
        db.mesh_nodes.create_index([("last_seen", -1)])            # liveness queries

        # telemetry - raw history
        db.telemetry.create_index([("node_id", 1), ("timestamp", -1)])  # per-node history
        db.telemetry.create_index([("timestamp", -1)])                 # time-window scans

        # route_reports - raw history
        db.route_reports.create_index([("node_id", 1), ("timestamp", -1)])
        db.route_reports.create_index([("timestamp", -1)])

        # blacklists - policy history
        db.blacklists.create_index([("timestamp", -1)])
        db.blacklists.create_index([("v", 1), ("sequence", 1)])

        state.state["database_client"] = client
        state.state["db"] = db
        return True
    except Exception as e:
        logger.log_error("setup_database", e)
        return False

# Closes database connection
def cleanup_database():
    state.state["database_client"].close() if state.state["database_client"] else None

# MQTT
def setup_mqtt():
    """Connect and start the network loop. Returns True/False."""
    try:
        client = mqtt.Client()
        client.on_connect = mqtt_handlers.on_connect
        client.on_message = mqtt_handlers.on_message
        client.on_disconnect = mqtt_handlers.on_disconnect
        client.connect(config.MQTT_BROKER, config.MQTT_PORT, keepalive=60)
        client.loop_start()   # network loop in a background thread
        return True
    except Exception as e:
        logger.log_error("setup_mqtt", e)
        return False

def cleanup_mqtt():
    client = mqtt_handlers.mqtt_client
    if client:
        client.loop_stop()
        client.disconnect()

# Redis
def setup_redis():
    """Connect to Redis. Returns True even when Redis is down - the
    parser continues in database-only mode (see main.py)."""
    try:
        redis_client = redis.from_url(config.REDIS_URL)
        redis_client.ping()   # from_url is lazy - ping forces a real connection
        state.state["redis"] = redis_client
    except Exception as e:
        state.state["redis"] = None
        logger.log_error("setup_redis", e)
    return True

# Close Redis connection
def cleanup_redis():
    redis_client = state.state["redis"]
    redis_client.close() if redis_client else None
    