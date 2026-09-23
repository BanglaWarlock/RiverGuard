"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

This file defines the MQTT message handling logic: 
what we subscribe to, and how an arriving message is
routed to the right handler in message_handler.py.

Adding a new message type = 
one line in SUBSCRIPTIONS, 
one line inprocess_message's routing table, 
one handle_* function. 
Nothing else in the program changes.
"""

import json
import threading
import state
import time

import paho.mqtt.client as mqtt

import message_handler

# The client object, set by connections.setup_mqtt's callback wiring.
# Kept as a module attribute (not in state.state) because only
# cleanup_mqtt needs it.
mqtt_client = None

# (topic pattern, QoS) - everything the parser listens for.
SUBSCRIPTIONS = [
    ("riverguard/+/battery/+", 1),
    ("riverguard/+/water/+", 1),
    ("riverguard/+/gps/+", 1),
    ("riverguard/+/signal/+", 1),
    ("riverguard/+/alert/+", 1),
    ("riverguard/+/announce/+", 1),
    ("riverguard/+/nodes/+/status", 1),
    ("riverguard/+/master/status", 1),
    ("riverguard/+/topology", 1),
]


def on_connect(client, userdata, flags, rc, props=None):
    """Callback when connected to MQTT broker (fires on first connect AND every reconnect)."""
    global mqtt_client
    mqtt_client = client

    if rc == 0:
        print("[MQTT] Connected to broker successfully!")
        for topic, qos in SUBSCRIPTIONS:
            client.subscribe(topic, qos=qos)
            print(f"  - Subscribed to: {topic}")
        print(f"[MQTT] Total subscriptions: {len(SUBSCRIPTIONS)}")
    else:
        print(f"[MQTT] Connection failed with result code {rc}")


def on_disconnect(client, userdata, rc, props=None):
    """Callback when disconnected. rc != 0 means unexpected - paho auto-retries."""
    if rc != 0:
        print(f"[MQTT] Unexpected disconnect (rc={rc}) - will retry")
    else:
        print("[MQTT] Disconnected gracefully")

# Spawns a thread when receiving a message.
def on_message(client, userdata, msg):
    """Callback when an MQTT message arrives. Spawns a thread to process it,
    so one slow database write never blocks the next message."""
    try:
        payload = msg.payload.decode("utf-8", errors="replace").strip()
        threading.Thread(
            target=process_message,
            args=(msg.topic, payload),
            daemon=True,
        ).start()
    except Exception as e:
        print(f"Error handling MQTT message: {e}\nPayload: {msg.payload}\nTopic: {msg.topic}")


def process_message(topic, payload):
    """Parse a topic and dispatch to the right handler. Runs in its own thread."""
    
    # to uncomment
    # print(f"\n[NEW MESSAGE] Topic: {topic}")
    
    # Increment the global message counter for stats
    state.message_count += 1  

    # Parse topic: riverguard/{village}/{msg_type}[/...]
    parts = topic.split("/")
    if len(parts) < 3:
        print("  - WARNING: Unrecognized topic format")
        return

    village = parts[1]
    msg_type = parts[2]

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        print(f"  - WARNING: Invalid JSON payload: {e}")
        return

    # ---- the routing table: msg_type -> handler ----
    try:
        if msg_type in message_handler.TELEMETRY_PARAMS and len(parts) == 4:
            message_handler.handle_telemetry(village, parts[3], msg_type, data)
        elif msg_type == "alert" and len(parts) == 4:
            message_handler.handle_alert(village, parts[3], data)
        elif msg_type == "announce" and len(parts) == 4:
            message_handler.handle_announce(village, parts[3], data)
        elif msg_type == "nodes" and len(parts) == 5 and parts[4] == "status":
            message_handler.handle_node_status(village, parts[3], data)
        elif msg_type == "master" and len(parts) == 4 and parts[3] == "status":
            message_handler.handle_master_status(village, data)
        elif msg_type == "topology" and len(parts) == 3:
            message_handler.handle_topology(village, data)
        else:
            print("  - WARNING: Unhandled message type")
    except Exception as e:
        # One bad message must never kill the processing thread silently
        print(f"  - ERROR: handler failed for '{msg_type}': {e}")