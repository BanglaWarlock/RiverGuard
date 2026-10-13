"""
RiverGuard simulator - one THREAD per node, one MQTT CLIENT per node.

ALWAYS FAST (demo/testing cadence): something happens every few
seconds. Real-time cadence was removed - history belongs to seed_db.py;
this is a LIVE demo on top.

Scenario-based: nodes, links, and route tables come from scenario.json
(the shared world - the same one seed_db seeds history for), computed
with real Dijkstra.

Every node is an independent MQTT client with its own connection -
node behavior is genuinely parallel, a dead thread is a dead node.

Per run, two random non-station nodes get a story:
  - a STRUGGLER: SF climbs 7 -> 12 over time (the "weak link" node)
  - a QUIET one: goes silent after ~2 minutes (the "stale node" story)

Contract-compliant publishing (docs/MQTT_MESSAGES.md):
  telemetry QoS 1, routes QoS 0, blacklist QoS 0 RETAINED.

Usage:
  python simulator.py
  python simulator.py --broker tay.suts.internal

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

# --- broker ---
BROKER = os.getenv("MQTT_BROKER", "localhost")
if "--broker" in sys.argv:
    BROKER = sys.argv[sys.argv.index("--broker") + 1]
PORT = 1883

# --- demo cadence (the only mode) ---
TICK = 0.1                    # loop ticks 10x per second
TELEMETRY_INTERVAL = 50       # a node's telemetry every ~5 s
ROUTE_INTERVAL = 80           # a route report every ~8 s
QUIET_AFTER = 120             # the quiet node falls silent after ~2 min
BLACKLIST_TICKS_PER_DAY = 30  # timeline "day" N -> policy change ~N*3 s

# --- scenario: shared with the seeder (one topology truth) ---
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "seeder"))
from generate_scenario import load, build_adjacency, compute_route_table

stop_event = threading.Event()

def signal_handler(signum, frame):
    stop_event.set()
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def make_client():
    """paho 1.x / 2.x compatible constructor (2.x requires the
    callback-API argument; 1.x has no such attribute)."""
    try:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    except AttributeError:
        return mqtt.Client()


class NodeThread(threading.Thread):
    """One node: its own MQTT client, its own cadence, its own state."""

    def __init__(self, node_id, route_table, struggle=False, quiet=False):
        super().__init__(daemon=True, name=node_id)
        self.id = node_id
        self.route_table = route_table
        self.struggle = struggle
        self.quiet = quiet
        self.client = make_client()
        # live state (accumulates like real counters)
        self.seq = 0
        self.topo_seq = 0
        self.tx = random.randint(20, 60)
        self.rx = 0
        self.txb = random.randint(800, 2400)
        self.rxb = 0
        self.up = random.randint(30, 90)
        self.sf = 7

    def publish(self, topic, payload, qos):
        self.client.publish(topic, json.dumps(payload), qos=qos)

    def telemetry(self):
        self.seq += 1
        sent = random.randint(6, 14)
        self.tx += sent
        self.rx += int(sent * random.uniform(0.82, 0.99))
        self.txb += sent * 41
        self.rxb += int(sent * 39)
        self.up += 5
        if self.struggle and self.sf < 12 and self.seq % 3 == 0:
            self.sf += 1          # the struggler: SF climbs toward 12
        self.publish(f"mesh/{self.id}/telemetry", {
            "node": self.id, "uptime_minute": self.up,
            "sequence": self.seq,
            "tx_packets": self.tx, "rx_packets": self.rx,
            "tx_bytes": self.txb, "rx_bytes": self.rxb,
            "sf": self.sf}, qos=1)

    def route_report(self):
        # the node's scenario route table, RSSI/SNR jittered per report
        self.topo_seq += 1
        routes = []
        for base in self.route_table:
            rt = dict(base)
            if rt.get("ri") is not None:
                rt["ri"] = rt["ri"] + random.randint(-3, 3)
                rt["sn"] = round(max(3.0, rt["sn"] - random.uniform(0, 1.5)), 1)
            routes.append(rt)
        self.publish(f"mesh/route/{self.id}",
                     {"s": self.topo_seq, "g": self.up * 60000,
                      "r": routes}, qos=0)

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
            stop_event.wait(TICK)          # interruptible
            elapsed += TICK
            tel_in += TICK
            route_in += TICK
            if self.quiet and elapsed >= QUIET_AFTER:
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


def policy_thread(station_id, timeline):
    """The station: runs the scenario's blacklist timeline on schedule,
    contract-style (QoS 0, retained - the broker keeps the latest)."""
    client = make_client()
    try:
        client.connect(BROKER, PORT, 60)
        client.loop_start()
    except Exception as e:
        print(f"[sim] station {station_id} could not connect: {e}")
        return
    prev_day = 0
    for entry in timeline:
        # wait the gap since the previous policy, not from t=0
        if stop_event.wait((entry["day"] - prev_day)
                           * BLACKLIST_TICKS_PER_DAY * TICK):
            break
        prev_day = entry["day"]
        payload = {k: entry[k] for k in ("v", "sequence", "edges")}
        client.publish("mesh/control/blacklist", json.dumps(payload),
                       qos=0, retain=True)
        print(f"[sim] {station_id}: policy seq {payload['sequence']} "
              f"({len(payload['edges'])} edge(s) disabled)")
    client.loop_stop()
    client.disconnect()


def main():
    random.seed()   # a live sim should be alive

    scenario = load()

    # route tables once per node - real Dijkstra over the scenario links
    nodes, route_tables = [], {}
    for island in scenario["islands"]:
        adj = build_adjacency(island["links"])
        for nid in island["nodes"] + [island["station"]]:
            nodes.append(nid)
            route_tables[nid] = compute_route_table(adj, nid)

    # the two stories: distinct, and never a station
    cast = [n for i in scenario["islands"] for n in i["nodes"]]
    struggler, quiet = random.sample(cast, 2)

    threads = []
    for nid in nodes:
        threads.append(NodeThread(
            nid, route_tables[nid],
            struggle=(nid == struggler), quiet=(nid == quiet)))

    for t in threads:
        t.start()
        time.sleep(0.05)   # staggered client connections, like real boots

    timeline = scenario.get("blacklist_timeline", [])
    if timeline:
        station = scenario["islands"][0]["station"]
        threading.Thread(target=policy_thread, args=(station, timeline),
                         daemon=True).start()

    print(f"[sim] {len(threads)} nodes live on {BROKER}:{PORT} (fast cadence)")
    print(f"[sim] struggler: {struggler} (SF will climb) | "
          f"quiet: {quiet} (silent after ~2 min)")
    print(f"[sim] watch: http://localhost:8000 - Stream tab live, "
          f"graph shows the stories. Ctrl+C to stop.")
    while not stop_event.is_set():
        stop_event.wait(1.0)

    print("[sim] stopped.")


if __name__ == "__main__":
    main()