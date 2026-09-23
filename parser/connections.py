"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

Connect to (and disconnect from) the three external systems:
MongoDB, the MQTT broker, and Redis.

The MQTT callbacks live in mqtt_handlers.py..
"""

import paho.mqtt.client as mqtt
from pymongo import MongoClient
import redis

import config
import state
import mqtt_handlers

import datetime



# MongoDB

# Connects to database 
# Creates indexes and resyncs counters. 
# Returns True/False.
def setup_database():
    """Connect to MongoDB, create indexes, resync counters. Returns True/False."""
    try:
        client = MongoClient(config.DB_URI)
        db = client[config.DB_NAME]

        # Indexes: lookup speed, prevents duplicate node docs from upsert
        # races, and speeds up the API's time-series queries.
        db.river_nodes.create_index([("node_id", 1), ("village_id", 1)], unique=True)
        db.river_nodes.create_index([("village_id", 1), ("status", 1)])
        db.river_nodes.create_index([("village_id", 1), ("parent_id", 1)])
        db.master_nodes.create_index([("node_id", 1)], unique=True)
        db.telemetry.create_index([("node_id", 1), ("timestamp", -1)])
        db.telemetry.create_index([("village_id", 1), ("param", 1), ("timestamp", -1)])
        db.alerts.create_index([("timestamp", -1)])
        db.events.create_index([("timestamp", -1)])

        # Resync global counters from actual collection state at startup.
        # Protects against drift (crash mid-update, manual deletes while testing).
        db.global_stats.update_one(
            {"_id": "global"},
            {"$set": {
                "masters_online": db.master_nodes.count_documents({"status": "online"}),
                "masters_offline": db.master_nodes.count_documents({"status": "offline"}),
                "river_nodes_online": db.river_nodes.count_documents({"status": "online"}),
                "river_nodes_offline": db.river_nodes.count_documents({"status": "offline"}),
                "updated_at": datetime.datetime.utcnow(),
            }},
            upsert=True,
        )

        db[config.LOG_COLLECTION].insert_one({
            "event": "program_start",
            "service": "parser",
            "message": "Parser service started and connected to MongoDB",
        })

        state.state["database_client"] = client
        state.state["db"] = db
        print(f"[Mongo] Connected to {config.DB_NAME} (indexes ready, stats resynced)")
        return True

    except Exception as e:
        print(f"[Mongo] Connection failed: {e}")
        return False

# Closes database connection
def cleanup_database():
    """Close MongoDB connection."""
    if state.state["database_client"]:
        state.state["database_client"].close()
        print("[Mongo] Connection closed")


# MQTT

# Connect to MQTT broker.
# Returns True/False.
def setup_mqtt():
    """Connect to the MQTT broker and start its network loop. Returns True/False."""
    print(f"[MQTT] Connecting to {config.MQTT_BROKER}:{config.MQTT_PORT}...")
    try:
        client = mqtt.Client()
        client.on_connect = mqtt_handlers.on_connect
        client.on_message = mqtt_handlers.on_message
        client.on_disconnect = mqtt_handlers.on_disconnect
        client.connect(config.MQTT_BROKER, config.MQTT_PORT, keepalive=60)
        client.loop_start()   # network loop in a background thread
        print("[MQTT] Event loop started")
        return True
    except Exception as e:
        print(f"[MQTT] Connection failed: {e}")
        return False

# Disconnect from MQTT broker.
def cleanup_mqtt():
    """Disconnect from MQTT broker. The client object is held by paho's loop."""
    client = mqtt_handlers.mqtt_client
    if client:
        client.loop_stop()
        client.disconnect()
        print("[MQTT] Disconnected from broker")


# Redis

# Connect to Redis. 
# Returns True even when Redis is down.
# When Redis is down, the parser continues to write to the database.
def setup_redis():
    """Connect to Redis. Optional: returns True even when Redis is down."""
    try:
        redis_client = redis.from_url(config.REDIS_URL)
        redis_client.ping()   # from_url is lazy - ping forces a real connection
        state.state["redis"] = redis_client
            # tood : uncomment
        # print(f"[Redis] Connected ({config.REDIS_URL})")
        return True
    except Exception as e:
        print(f"[Redis] Connection failed: {e} - continuing without Redis")
        print("[Redis] (database writes continue, no real-time notifications)")
        return True   # NOT fatal: see main.py for why DB is different

# Closes Redis connection
def cleanup_redis():
    """Close Redis connection."""
    if state.state["redis"]:
        state.state["redis"].close()
        print("[Redis] Connection closed")