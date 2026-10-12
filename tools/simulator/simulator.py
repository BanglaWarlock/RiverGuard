"""
RiverGuard simulator - one THREAD per node, one MQTT CLIENT per node.

Faithful to the real architecture: every node is an independent MQTT
client with its own connection, so node behavior is genuinely parallel,
a dead thread is a dead node, and a master outage is simply that
island's clients losing their broker path.

Two islands (from the seeder's scenario), each node simulating:
  telemetry (counters accumulating, uptime growing, SF evolving)
  route reports (per-node table, jittered RSSIs - imported from the
                 seeder's scenario, one source of topology truth)
  blacklist evolution (island A only, station-side)
  one quiet node (island B) that goes silent after a while

Usage:
  python simulator.py                        # real cadence (5 min telemetry)
  python simulator.py --fast                 # demo cadence: something
                                             # changes every few seconds
  python simulator.py --broker tay.suts.internal --fast
                                             # point at the gateway stack

Ctrl+C stops all threads cleanly.
"""

import json
import os
import random
import signal
import sys
import threading
import time

import paho.mqtt.client as mqtt

# --- broker (env var, or --broker flag) ---
BROKER = os.getenv("MQTT_BROKER", "localhost")
if "--broker" in sys.argv:
    BROKER = sys.argv[sys.argv.index("--broker") + 1]
PORT = 1883

# --- speed ---
FAST = "--fast" in sys.argv
if FAST:
    TICK = 0.1                    # the loop ticks 10x per real second
    TELEMETRY_INTERVAL = 50       # -> a node's telemetry every ~5s
    ROUTE_INTERVAL = 80           # -> a route report every ~8s
    QUIET_AFTER = 120             # quiet node silent after ~2 min
    BLACKLIST_SCRIPT = [
        (30,  {"v": 1, "sequence": 5, "edges": [["0123ABCD", "AABBCCDD"]]}),
        (90,  {"v": 1, "sequence": 6, "edges": [["0123ABCD", "AABBCCDD"],
                                                ["44556677", "89ABCDEF"]]}),
        (180, {"v": 2, "sequence": 7, "edges": [["0123ABCD", "AABBCCDD"]],
               "reason": "link_quality"}),
    ]
else:
    TICK = 1.0                    # real time
    TELEMETRY_INTERVAL = 300      # 5 min per node, per the firmware contract
    ROUTE_INTERVAL = 600
    QUIET_AFTER = 1800
    BLACKLIST_SCRIPT = [
        (600,  {"v": 1, "sequence": 5, "edges": [["0123ABCD", "AABBCCDD"]]}),
        (1800, {"v": 1, "sequence": 6, "edges": [["0123ABCD", "AABBCCDD"],
                                                 ["44556677", "89ABCDEF"]]}),
        (3600, {"v": 2, "sequence": 7, "edges": [["0123ABCD", "AABBCCDD"]],
                "reason": "link_quality"}),
    ]

# --- scenario: shared with the seeder (one topology truth) ---
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "seeder"))
from seed_data import ISLAND_A, ISLAND_B, BASE_RSSI, \
    island_a_routes, island_b_routes

ALL_ISLANDS = [ISLAND_A, ISLAND_B]
ROUTE_TABLES = dict(island_a_routes() + island_b_routes())  # node_id -> {"r": [...]}

SF_CLIMB = {"AABBCCDD": [9, 10, 11, 12]}   # SF per telemetry, then holds

stop_event = threading.Event()

def signal_handler(signum, frame):
    stop_event.set()
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


class NodeThread(threading.Thread):
    """One node: its own MQTT client, its own cadence, its own state."""

    def __init__(self, node_id, island):
        super().__init__(daemon=True, name=node_id)
        self.id = node_id
        self.island = island
        self.client = mqtt.Client()
        # live state (accumulates like the seeder's counters)
        self.seq = 0
        self.tx = random.randint(20, 60)
        self.rx = 0
        self.txb = random.randint(800, 2400)
        self.rxb = 0
        self.up = random.randint(30, 90)
        self.sf_idx = 0

    def publish(self, topic, payload):
        self.client.publish(topic, json.dumps(payload), qos=1)

    def telemetry(self):
        self.seq += 1
        tx = random.randint(6, 14)
        self.tx += tx
        self.rx += int(tx * random.uniform(0.82, 0.99))
        self.txb += tx * 41
        self.rxb += int(tx * 39)
        self.up += 5
        climb = SF_CLIMB.get(self.id)
        sf = climb[min(self.sf_idx, len(climb) - 1)] if climb else 7
        self.sf_idx += 1
        self.publish(f"mesh/{self.id}/telemetry", {
            "node": self.id, "uptime_minute": self.up, "sequence": self.seq,
            "tx_packets": self.tx, "rx_packets": self.rx,
            "tx_bytes": self.txb, "rx_bytes": self.rxb,
            "sf": sf})

    def route_report(self):
        # the REAL route table from the seeder's scenario, jittered per report
        routes = []
        for base in ROUTE_TABLES.get(self.id, {}).get("r", []):
            rt = dict(base)
            if rt.get("ri") is not None:
                rt["ri"] = rt["ri"] + random.randint(-3, 3)
                rt["sn"] = round(max(3.0, rt["sn"] - random.uniform(0, 1.5)), 1)
            routes.append(rt)
        self.publish(f"mesh/route/{self.id}",
                     {"s": self.seq, "g": int(time.time() * 1000),
                      "r": routes})

    def run(self):
        try:
            self.client.connect(BROKER, PORT, 60)
            self.client.loop_start()
        except Exception as e:
            print(f"[sim] {self.id} could not connect: {e}")
            return
        time.sleep(random.uniform(0, 3 * TICK))     # staggered starts
        tel_in, route_in = 0.0, random.uniform(0, ROUTE_INTERVAL)
        elapsed = 0.0
        while not stop_event.is_set():
            stop_event.wait(TICK)          # interruptible AND speed-scaled
            elapsed += TICK
            tel_in += TICK
            route_in += TICK
            if self.island.get("quiet") == self.id and elapsed >= QUIET_AFTER:
                print(f"[sim] {self.id} went silent")
                break
            if tel_in >= TELEMETRY_INTERVAL:
                tel_in = 0.0
                self.telemetry()
            if route_in >= ROUTE_INTERVAL:
                route_in = 0.0
                self.route_report()
        self.client.loop_stop()
        self.client.disconnect()


def station_thread(station_id):
    """Island A's station: runs the blacklist script on schedule."""
    client = mqtt.Client()
    try:
        client.connect(BROKER, PORT, 60)
        client.loop_start()
    except Exception as e:
        print(f"[sim] station {station_id} could not connect: {e}")
        return
    for delay, policy in BLACKLIST_SCRIPT:
        if stop_event.wait(delay * TICK):
            break
        client.publish("mesh/control/blacklist", json.dumps(policy), qos=1)
        print(f"[sim] station {station_id}: blacklist seq {policy['sequence']}")
    client.loop_stop()
    client.disconnect()


def main():
    random.seed()   # a live sim should be alive

    threads = []
    for island in ALL_ISLANDS:
        for node_id in island["nodes"]:
            threads.append(NodeThread(node_id, island))

    for t in threads:
        t.start()
        time.sleep(0.3)   # staggered client connections, like real boots

    bl = threading.Thread(target=station_thread,
                          args=(ISLAND_A["station"],), daemon=True)
    bl.start()

    print(f"[sim] {len(threads)} nodes live on {BROKER}:{PORT}, "
          f"{'FAST' if FAST else 'real'} cadence. Ctrl+C to stop.")
    while not stop_event.is_set():
        stop_event.wait(1.0)

    print("[sim] stopped.")


if __name__ == "__main__":
    main()