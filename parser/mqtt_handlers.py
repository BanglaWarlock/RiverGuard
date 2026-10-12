"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

This file defines the MQTT message handling logic: 
what we subscribe to, and how an arriving message is
routed to the right handler in message_handler.py.

Adding a new message type = 
one line in SUBSCRIPTIONS, 
one line in process_message's routing table, 
one handle_* function. 
Nothing else in the program changes.
"""
import json
import threading
import message_handler
import logger

# The client object, set by connections.setup_mqtt's callback wiring.
# Kept as a module attribute (not in state.state) because only
# cleanup_mqtt needs it.
mqtt_client = None

# (topic pattern, QoS) - everything the parser listens for.
SUBSCRIPTIONS = [
    ("mesh/+/telemetry", 1),
    ("mesh/route/+", 1),
    ("mesh/control/blacklist", 1),]

def on_connect(client, userdata, flags, rc, props=None):
    global mqtt_client
    mqtt_client = client

    if rc == 0:
        for topic, qos in SUBSCRIPTIONS:
            client.subscribe(topic, qos=qos)
    else:
        pass

def on_disconnect(client, userdata, rc, props=None):
    if rc != 0:
        logger.log_error("on_disconnect", f"Unexpected disconnect (rc={rc}) - will retry")
    else:
        pass

# Callback when an MQTT message arrives. 
# Spawns a thread to process it, so one slow database write never blocks the next message.
def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode("utf-8", errors="replace").strip()
        threading.Thread(
            target=process_message,
            args=(msg.topic, payload),
            daemon=True,
        ).start()
    except Exception as e:
        logger.log_error("on_message", e)

# Dispatch a message to the right handler
# Runs in its own thread.
def process_message(topic, payload):
    parts = topic.split("/")

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        logger.log_error("json_loader", e)
        return

    # ---- the routing table: msg_type -> handler ----
    try:
        # mesh/{node}/telemetry
        if (len(parts) == 3 and parts[0] == "mesh" and parts[2] == "telemetry"):
            message_handler.handle_mesh_telemetry(parts[1], data)

        # mesh/route/{node}
        elif (len(parts) == 3 and parts[0] == "mesh" and parts[1] == "route"):
            message_handler.handle_mesh_route(parts[2], data)

        # mesh/control/blacklist
        elif (len(parts) == 3 and parts[0] == "mesh" and parts[1] == "control"
              and parts[2] == "blacklist"):
            message_handler.handle_mesh_blacklist(data)

        else:
            logger.log_error("no route", topic)
            

    except Exception as e:
        logger.log_error("mqtt_handler", e)