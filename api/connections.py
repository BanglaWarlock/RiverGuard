"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

Connect to (and disconnect from): MongoDB and Redis. 

Note the asymmetry, which is deliberate:
  MongoDB is REQUIRED  -> setup raises, the API refuses to start without it
  Redis is OPTIONAL   -> setup returns quietly, /stream returns 503
"""

from pymongo import MongoClient
import redis.asyncio as aioredis

import config
import state

# Database
"""Connect to MongoDB. Raises on failure - REST is the whole point
of this service, so there is no degraded mode to run in."""
async def setup_database():
    client = MongoClient(config.DB_URI)
    db = client[config.DB_NAME]
    db.command("ping")   # connections are lazy - ping forces a real one
    state.state["mongo"] = client
    state.state["db"] = db
    print(f"[Mongo] Connected to {config.DB_NAME}")

"""Close the MongoDB connection."""
def cleanup_database():
    if state.state["mongo"]:
        state.state["mongo"].close()
        print("[Mongo] Connection closed")

# Redis
"""Connect to Redis (optional). On failure, leaves redis as None -
REST keeps working, /stream returns 503 until restart."""
async def setup_redis():
    try:
        client = aioredis.from_url(config.REDIS_URL)
        await client.ping()
        state.state["redis"] = client
        print(f"[Redis] Connected ({config.REDIS_URL})")
    except Exception as e:
        state.state["redis"] = None
        print(f"[Redis] Connection failed: {e} - /stream will return 503")

"""Close the Redis connection."""
async def cleanup_redis():
    if state.state["redis"]:
        await state.state["redis"].aclose()
        print("[Redis] Connection closed")