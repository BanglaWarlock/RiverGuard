"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

Publish to Redis - the parser's notification to the API.
Pub/sub stores NOTHING: if Redis is down, the message is simply not
delivered; the database remains the source of truth.
"""

import json
import state
import logger

# One JSON message on a channel. No-op if Redis is down.
def publish(channel, message):
    redis_client = state.state["redis"]
    if redis_client is None:
        return
    try:
        redis_client.publish(channel, json.dumps(message))
    except Exception as e:
        logger.log_error(f"redis publish {channel}", e)