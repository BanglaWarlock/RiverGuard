"""
Publish a burst of scenario-based messages to MQTT - live pipeline test.
(broker -> parser -> database -> Redis -> API -> website: open the
website's Stream tab and watch each event arrive live.)

Everything comes from scenario.json - the same shared world seed_db.py
seeds history for. This tool publishes "now" messages only: the parser
stamps arrival time, so MQTT seeding is a LIVE demo, not history
(that's seed_db.py's job - run both: history in the DB, live events
on top).

What gets published, per the contract (docs/MQTT_MESSAGES.md):
  - mesh/{node}/telemetry   (QoS 1)   counters accumulate across the burst
  - mesh/route/{node}       (QoS 0)   full route table, real Dijkstra
  - mesh/control/blacklist  (QoS 0, RETAINED)  the scenario's policy
    timeline in order; the broker retains the last one, exactly like
    the station updating policy over time.

Run it TWICE for the full demo: the second run's blacklist is a
retained re-delivery of the same v+sequence - the parser recognizes
and skips it (the dedup path, live).

Usage:
  python seed_mqtt.py                 # 3 telemetry per node
  python seed_mqtt.py --per-node 5
  python seed_mqtt.py --delay 0.05    # faster burst
"""

import json
import random
import sys
import time

import paho.mqtt.client as mqtt

from generate_scenario import load, build_adjacency, compute_route_table

BROKER, PORT = "localhost", 1883
PER_NODE_DEFAULT = 3
DELAY_DEFAULT = 0.15


def make_client():
    """paho 1.x / 2.x compatible constructor (2.x requires the
    callback-API argument; 1.x has no such attribute)."""
    try:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    except AttributeError:
        return mqtt.Client()


def build_telemetry(counters, node_id):
    """One telemetry message. Mutates the node's counters - cumulative,
    monotonically increasing, per the contract."""
    c = counters[node_id]
    c["seq"] += 1
    sent = random.randint(6, 14)
    c["tx"] += sent
    c["rx"] += int(sent * random.uniform(0.85, 0.99))
    c["txb"] += sent * 41
    c["rxb"] += int(sent * 39)
    c["up"] += random.randint(3, 8)
    return {
        "node": node_id,
        "uptime_minute": c["up"],
        "sequence": c["seq"],
        "tx_packets": c["tx"],
        "rx_packets": c["rx"],
        "tx_bytes": c["txb"],
        "rx_bytes": c["rxb"],
        "sf": c["sf"],
    }


def main():
    per_node, delay = PER_NODE_DEFAULT, DELAY_DEFAULT
    if "--per-node" in sys.argv:
        per_node = int(sys.argv[sys.argv.index("--per-node") + 1])
    if "--delay" in sys.argv:
        delay = float(sys.argv[sys.argv.index("--delay") + 1])

    scenario = load()

    nodes = []
    for island in scenario["islands"]:
        nodes += island["nodes"] + [island["station"]]

    # route tables once, per node - real Dijkstra over the scenario links
    route_tables = {}
    for island in scenario["islands"]:
        adj = build_adjacency(island["links"])
        for nid in island["nodes"] + [island["station"]]:
            route_tables[nid] = compute_route_table(adj, nid)

    # per-node live counters (the burst's little lifecycle)
    counters = {nid: {
        "seq": 0, "tx": random.randint(20, 60), "rx": 0,
        "txb": random.randint(800, 2400), "rxb": 0,
        "up": random.randint(30, 90), "sf": random.randint(7, 12),
    } for nid in nodes}

    c = make_client()
    c.connect(BROKER, PORT, 60)
    c.loop_start()
    time.sleep(0.5)

    published = []

    # 1. telemetry: round-robin, so the stream tab shows nodes interleaved
    for _ in range(per_node):
        for nid in nodes:
            payload = build_telemetry(counters, nid)
            published.append(c.publish(
                f"mesh/{nid}/telemetry", json.dumps(payload), qos=1))
            time.sleep(delay)

    # 2. route reports: one per node
    for nid in nodes:
        payload = {"s": 10, "g": counters[nid]["up"] * 60000,
                   "r": route_tables[nid]}
        published.append(c.publish(
            f"mesh/route/{nid}", json.dumps(payload), qos=0))
        time.sleep(delay)

    # 3. blacklist timeline in order - each retained; the broker keeps
    #    the last, mimicking the station updating policy over time.
    #    (v/sequence/edges only - any extra scenario keys stay out of
    #    the wire format)
    for entry in scenario.get("blacklist_timeline", []):
        payload = {k: entry[k] for k in ("v", "sequence", "edges")}
        published.append(c.publish(
            "mesh/control/blacklist", json.dumps(payload),
            qos=0, retain=True))
        time.sleep(delay * 2)

    for info in published:      # let QoS 1 messages finish before exiting
        info.wait_for_publish()
    c.loop_stop()
    c.disconnect()

    bl_count = len(scenario.get("blacklist_timeline", []))
    print(f"Published {len(nodes) * per_node} telemetry, "
          f"{len(nodes)} route reports, {bl_count} blacklists (retained).")
    print("[mqtt] watch live: website Stream tab (http://localhost:8000)")
    print("[mqtt] run me again - the retained blacklist gets deduped "
          f"by the parser (same v+sequence, skipped by design)")


if __name__ == "__main__":
    main()