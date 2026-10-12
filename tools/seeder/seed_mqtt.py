"""
Publish ONE DAY of the demo scenario to MQTT - live pipeline test.
(broker -> parser -> database -> Redis -> API -> website, watch the
stream tab catch each event).

History/multi-day is a DATABASE concept (seed_db.py); MQTT messages
are stamped on arrival by the parser, so only today's data makes sense
here.
"""

import json, time
import paho.mqtt.client as mqtt
from seed_data import generate

BROKER, PORT = "localhost", 1883

def main():
    telemetry, routes, blacklists = generate(days=1, per_day=2)

    c = mqtt.Client()
    c.connect(BROKER, PORT, 60)
    c.loop_start()
    time.sleep(0.5)

    for node_id, payload, day in telemetry:
        c.publish(f"mesh/{node_id}/telemetry", json.dumps(payload), qos=1)
        time.sleep(0.15)
    for node_id, payload, day in routes:
        c.publish(f"mesh/route/{node_id}", json.dumps(payload), qos=1)
        time.sleep(0.15)
    for _, bl, day in blacklists:
        c.publish("mesh/control/blacklist", json.dumps(bl), qos=1)
        time.sleep(0.3)

    print(f"Published {len(telemetry)} telemetry, {len(routes)} routes, "
          f"{len(blacklists)} blacklists (one day, live).")
    c.loop_stop(); c.disconnect()

if __name__ == "__main__":
    main()