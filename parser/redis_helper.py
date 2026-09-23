"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

This file contains helper functions for handling Redis communication.

Reminder: pub/sub stores NOTHING. If Redis is down, or the API isn't
subscribed at this exact moment, the message is gone - which is fine,
because the database is the source of truth and Redis is only the
"something just happened" tap on the shoulder.
"""

import json
import state

"""Publish one JSON message on a Redis channel.
    No-op (with warning) if Redis is down - database writes already succeeded."""
def publish(channel, message):
    redis_client = state.state["redis"]
    if redis_client is None:
        return
    try:
        redis_client.publish(channel, json.dumps(message))
    except Exception as e:
        print(f"  - [Redis] publish to {channel} failed: {e}")