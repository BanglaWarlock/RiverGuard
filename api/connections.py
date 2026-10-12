"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

Connect to (and disconnect from): MongoDB and Redis.

  MongoDB is REQUIRED -> setup raises, the API refuses to start without it
  Redis is OPTIONAL   -> setup continues, /stream returns 503
"""

from pymongo import MongoClient
import redis.asyncio as aioredis

import config
import state
import logger


def setup_database():
    """Connect to MongoDB. Raises on failure."""
    client = MongoClient(config.DB_URI)
    db = client[config.DB_NAME]
    db.command("ping")   # connections are lazy - ping forces a real one
    state.state["mongo"] = client
    state.state["db"] = db

def cleanup_database():
    state.state["mongo"].close() if state.state["mongo"] else None

async def setup_redis():
    """Connect to Redis (optional). On failure, leaves redis as None -
    REST keeps working, /stream returns 503 until restart."""
    try:
        client = aioredis.from_url(config.REDIS_URL)
        await client.ping()
        state.state["redis"] = client
    except Exception as e:
        state.state["redis"] = None
        logger.log_error("setup_redis", e)

async def cleanup_redis():
    await state.state["redis"].aclose() if state.state["redis"] else None