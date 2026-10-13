"""
Seed the database with history generated from the shared scenario.

Reads scenario.json and generates a LIVING history:

  - EDGE telemetry (the dense stream): every link's RSSI/SNR sampled
    every 10 minutes (~144 per edge per day), spread evenly, with
    drift + degradation events. Storage shape: `param`/`value` rows
    ("edge.<node>.rssi") - the firmware contract does not yet define
    a dense edge-quality message, so this models the future stream in
    the same collection. Nothing downstream consumes it yet; it is
    analysis fodder.
  - NODE telemetry (the sparse stream): counters/uptime/SF, ~10 per
    node per day, STORED IN THE PARSER'S EXACT SHAPE (verbatim
    payload) - the reporter and API see seeded and real data
    identically.
  - Route reports: ONE per node per day (the contract's periodic
    report), computed from that day's FINAL edge samples,
    blacklist-filtered. Sparse by design - routes are derived data.
  - Blacklist timeline as-is; blacklisted edges are excluded from
    routing on their active days (routes re-route around them).
  - mesh_nodes: final snapshots in the SAME field set the parser
    writes (telemetry_seq, tx/rx packets AND bytes, topology_seq,
    link_count, first-hop quality, last_seen at the day's last
    message).

Usage:
  python seed_db.py                 # 5 days, edge every 10 min, node ~10/day
  python seed_db.py --days 3
  python seed_db.py --edge-min 20   # every 20 min -> 72/edge/day
"""

import datetime
import random
import sys

from pymongo import MongoClient
from generate_scenario import (load, build_adjacency, dijkstra)

DB_URI, DB_NAME = "mongodb://localhost:27017", "RiverGuard"

DEGRADE_CHANCE = 0.12          # chance of entering degradation, PER DAY
DEGRADE_SHIFT = 12.0
DRIFT_JITTER = 2.0

RSSI_MIN, RSSI_MAX = -105.0, -48.0     # matches the generator's model
SNR_MIN, SNR_MAX = 2.0, 12.0

EDGE_MINUTES_DEFAULT = 10       # 144 samples per edge per day
PER_NODE_DEFAULT = 10

ASYM_DB = 3.0     # per-direction baseline offset (dB) - link asymmetry
ASYM_SNR = 0.8    # per-direction baseline offset (dB)

REPORT_MINUTES_DEFAULT = 10   # one route report per node per hour


# --- time helpers ---

def day_start(day):
    """UTC midnight of day N (1=today, 2=yesterday...)."""
    now = datetime.datetime.utcnow()
    base = now - datetime.timedelta(days=day - 1)
    return base.replace(hour=0, minute=0, second=0, microsecond=0)

def ts_in_day(day, minutes_offset):
    return day_start(day) + datetime.timedelta(minutes=minutes_offset)


# --- per-step edge quality model ---

def edge_sample(baseline, state, key, chance_per_step, edge_min):
    """
    One quality sample for one edge: a mean-reverting random walk
    around the baseline + degradation events (2-6 hours, then recover).
    `state[key]` carries the walk, so the series is continuous.
    """
    s = state.setdefault(key, {"rssi": baseline["rssi"],
                               "snr": baseline["snr"],
                               "degraded_for": 0})

    if s["degraded_for"] > 0:
        s["degraded_for"] -= 1
    elif random.random() < chance_per_step:
        s["degraded_for"] = random.randint(
            int(2 * 60 / edge_min), int(6 * 60 / edge_min))

    drift = (-DEGRADE_SHIFT * 0.15 if s["degraded_for"] > 0 else 0.0)
    rssi = s["rssi"] + random.gauss(drift, DRIFT_JITTER * 0.3)
    snr = s["snr"] + random.gauss(-0.6 if s["degraded_for"] > 0 else 0.0, 0.4)

    # mean-revert toward the baseline
    s["rssi"] = 0.95 * s["rssi"] + 0.05 * baseline["rssi"] + (rssi - s["rssi"])
    s["snr"] = 0.95 * s["snr"] + 0.05 * baseline["snr"] + (snr - s["snr"])

    return (round(max(RSSI_MIN, min(RSSI_MAX, rssi)), 1),
            round(max(SNR_MIN, min(SNR_MAX, snr)), 1))


def cost_from(rssi, snr):
    """The generator's cost model - kept identical."""
    rssi_norm = (rssi - (-105.0)) / ((-48.0) - (-105.0))
    snr_norm = (snr - 2.0) / (13.0 - 2.0)
    return round(10.0 * (1.0 - (rssi_norm + snr_norm) / 2), 1)


def blacklist_on(timeline, day):
    active = [e for e in timeline if e["day"] <= day]
    if not active:
        return []
    return max(active, key=lambda e: e["sequence"])["edges"]


# --- seeding ---

def seed(db, scenario, days, per_node, report_min):
    """The ONE orchestration path. Route reports are the dense stream:
    one per node per report_min, each computed from that moment's
    directional link qualities. There is no separate edge stream."""
    timeline = [e for e in scenario.get("blacklist_timeline", [])
                if e["day"] <= days]

    for island in scenario["islands"]:
        last_reports = seed_routes(db, island, days, timeline, report_min)
        seed_node_telemetry(db, island, days, per_node)
        seed_mesh_nodes(db, island, last_reports)
        print(f"[seed] {island['name']}: done")

    seed_blacklists(db, scenario, days)


def seed_edge_telemetry(db, island, days, edge_min):
    """
    The DENSE stream, both directions: each node stores its own
    measurement of each neighbor - node X's rows are
    param "edge.<Y>.rssi" = how X hears Y. RETURNS history
    {day: {"observer>subject": (rssi, snr, cost)}} for route
    computation. Rows batched one insert_many per island-day.
    """
    edge_state, dir_state, history = {}, {}, {}
    links = island["links"]
    steps_per_day = (24 * 60) // edge_min
    chance_per_step = DEGRADE_CHANCE / steps_per_day

    for day in range(days, 0, -1):
        day_last, batch = {}, []
        for step in range(steps_per_day):
            ts = ts_in_day(day, step * edge_min + edge_min // 2)
            for l in links:
                both = step_edge(l, edge_state, dir_state,
                                 chance_per_step, edge_min)
                for key, (rssi, snr) in both.items():
                    observer, subject = key.split(">")
                    cost = cost_from(rssi, snr)
                    day_last[key] = (rssi, snr, cost)
                    batch += [
                        {"node_id": observer,
                         "param": f"edge.{subject}.rssi",
                         "value": rssi, "timestamp": ts},
                        {"node_id": observer,
                         "param": f"edge.{subject}.snr",
                         "value": snr, "timestamp": ts},
                        {"node_id": observer,
                         "param": f"edge.{subject}.cost",
                         "value": cost, "timestamp": ts},
                    ]
        db.telemetry.insert_many(batch)
        history[day] = day_last

    return history


def seed_node_telemetry(db, island, days, per_node):
    """
    The SPARSE stream: node counters, per_node per day - in the
    PARSER'S EXACT SHAPE (verbatim payload), so reporter/API treat
    seeded and real data identically. Timestamps stay before 22:00 so
    the day's route report (23:59) is always the node's last message.
    """
    for node_id in island["nodes"] + [island["station"]]:
        seq = 0
        tx = random.randint(20, 60)
        rx = 0
        txb = random.randint(800, 2400)
        rxb = 0
        up = random.randint(30, 90)
        sf = random.randint(7, 12)

        for day in range(days, 0, -1):
            for _ in range(per_node):
                seq += 1
                sent = random.randint(6, 14)
                tx += sent
                rx += int(sent * random.uniform(0.85, 0.99))
                txb += sent * 41
                rxb += int(sent * 39)
                up += 24 * 60 // per_node

                ts = ts_in_day(day, random.randint(0, 22 * 60))
                db.telemetry.insert_one({
                    "node_id": node_id,
                    "payload": {
                        "node": node_id, "uptime_minute": up,
                        "sequence": seq,
                        "tx_packets": tx, "rx_packets": rx,
                        "tx_bytes": txb, "rx_bytes": rxb,
                        "sf": sf,
                    },
                    "timestamp": ts,
                })

        db.mesh_nodes.update_one(
            {"node_id": node_id},
            {"$set": {"telemetry_seq": seq, "uptime_minute": up, "sf": sf,
                      "tx_packets": tx, "rx_packets": rx,
                      "tx_bytes": txb, "rx_bytes": rxb},
             "$setOnInsert": {"node_id": node_id,
                              "first_seen": day_start(days)}},
            upsert=True)


def seed_routes(db, island, days, timeline, report_min):
    """
    The dense stream, in the contract's own message: one route report
    per node per report_min, computed from a live directional quality
    walk (shared per-edge degradation, per-direction baselines/jitter
    - the same model as before, just carried by route reports now).
    Every ri/sn in every report is a real sample of that link at that
    moment. RETURNS each node's final report, for mesh_nodes.

    Routing convention (unchanged): the cost of hop X->Y is X's own
    measurement of Y - each node routes on what it hears.
    """
    edge_state, dir_state = {}, {}
    links = island["links"]
    nodes = island["nodes"] + [island["station"]]
    steps_per_day = (24 * 60) // report_min
    chance = DEGRADE_CHANCE / steps_per_day
    topo_seq = {nid: 0 for nid in nodes}
    boot_ms = {nid: random.randint(0, 90) * 60000 for nid in nodes}  # per-node boot offset
    last_reports = {}
    batch = []

    for day in range(days, 0, -1):
        banned = {frozenset(e) for e in blacklist_on(timeline, day)}
        for step in range(steps_per_day):
            ts = ts_in_day(day, step * report_min + report_min // 2)
            uptime_ms = int((ts - day_start(days)).total_seconds() * 1000)

            # directional adjacency from THIS step's samples
            adj = {}
            for l in links:
                if frozenset((l["a"], l["b"])) in banned:
                    continue
                both = step_edge(l, edge_state, dir_state, chance, report_min)
                a, b = l["a"], l["b"]
                rssi_a, snr_a = both[f"{a}>{b}"]   # a's view of b
                rssi_b, snr_b = both[f"{b}>{a}"]   # b's view of a
                adj.setdefault(a, []).append(
                    (b, cost_from(rssi_a, snr_a), rssi_a, snr_a))
                adj.setdefault(b, []).append(
                    (a, cost_from(rssi_b, snr_b), rssi_b, snr_b))

            for node_id in nodes:
                topo_seq[node_id] += 1
                routes = dijkstra(adj, node_id)
                table = []
                for dest, info in routes.items():
                    first_hop = info["next_hop"]
                    link = next((li for li in adj.get(node_id, [])
                                 if li[0] == first_hop), None)
                    table.append({
                        "d": dest, "n": first_hop, "h": info["hops"],
                        "c": info["cost"], "l": link[1] if link else None,
                        "ri": link[2] if link else None,
                        "sn": link[3] if link else None,
                        "p": ">".join(info["path"]),
                        "a": random.randint(400, 3000),
                        "q": random.randint(10, 50),
                    })
                report = {
                    "node_id": node_id,
                    "payload": {"s": topo_seq[node_id],
                                "g": uptime_ms + boot_ms[node_id],
                                "r": table},
                    "timestamp": ts,
                }
                batch.append(report)
                last_reports[node_id] = report   # later steps overwrite

        db.route_reports.insert_many(batch)
        batch = []

    return last_reports

def seed_mesh_nodes(db, island, last_reports):
    """Final snapshots - replicating the PARSER's own logic
    (upsert_mesh_node_from_route): topology_seq from s, link_count
    from the table, first-hop quality from the first non-null ri.
    Seeded and real mesh_nodes docs are indistinguishable."""
    for node_id, report in last_reports.items():
        p = report["payload"]
        routes = p.get("r", [])
        first_hop = next((r for r in routes if r.get("ri") is not None), None)
        db.mesh_nodes.update_one(
            {"node_id": node_id},
            {"$set": {
                "last_seen": report["timestamp"],
                "topology_seq": p.get("s"),
                "link_count": len(routes),
                "first_hop_rssi": first_hop.get("ri") if first_hop else None,
                "first_hop_snr": first_hop.get("sn") if first_hop else None,
            },
             "$setOnInsert": {"node_id": node_id,
                              "first_seen": report["timestamp"]}},
            upsert=True)


def seed_blacklists(db, scenario, days):
    timeline = [e for e in scenario.get("blacklist_timeline", [])
                if e["day"] <= days]
    for entry in timeline:
        db.blacklists.insert_one({
            "v": entry["v"], "sequence": entry["sequence"],
            "edges": entry["edges"],
            "timestamp": ts_in_day(entry["day"], 12 * 60),
        })
    if timeline:
        latest = max(timeline, key=lambda e: e["sequence"])
        db.current_blacklist.update_one(
            {"_id": "active"},
            {"$set": {"v": latest["v"], "sequence": latest["sequence"],
                      "edges": latest["edges"],
                      "received": ts_in_day(1, 12 * 60)}},
            upsert=True)
        
# --- per-step edge quality model (DIRECTIONAL) ---

def step_edge(link, edge_state, dir_state, chance_per_step, edge_min):
    """
    Advance ONE edge one step. Returns {key: (rssi, snr)} where key is
    "observer>subject" - "how observer hears subject" - for BOTH
    directions. A->B and B->A are independent walks with their own
    baselines (asymmetric link), but DEGRADATION is shared per edge:
    an obstruction degrades both directions together.
    """
    ek = frozenset((link["a"], link["b"]))
    e = edge_state.setdefault(ek, {"degraded_for": 0})
    if e["degraded_for"] > 0:
        e["degraded_for"] -= 1
    elif random.random() < chance_per_step:
        e["degraded_for"] = random.randint(
            int(2 * 60 / edge_min), int(6 * 60 / edge_min))
    degraded = e["degraded_for"] > 0

    out = {}
    for observer, subject in ((link["a"], link["b"]), (link["b"], link["a"])):
        key = f"{observer}>{subject}"
        if key not in dir_state:
            # this direction's own baseline: nominal +- asymmetry
            off_r = random.gauss(0, ASYM_DB)
            off_s = random.gauss(0, ASYM_SNR)
            dir_state[key] = {
                "base_rssi": link["rssi"] + off_r,
                "base_snr": link["snr"] + off_s,
                "rssi": link["rssi"] + off_r,
                "snr": link["snr"] + off_s,
            }
        s = dir_state[key]

        drift = (-DEGRADE_SHIFT * 0.15 if degraded else 0.0)
        rssi = s["rssi"] + random.gauss(drift, DRIFT_JITTER * 0.3)
        snr = s["snr"] + random.gauss(-0.6 if degraded else 0.0, 0.4)

        # mean-revert toward THIS direction's baseline
        s["rssi"] = 0.95 * s["rssi"] + 0.05 * s["base_rssi"] + (rssi - s["rssi"])
        s["snr"] = 0.95 * s["snr"] + 0.05 * s["base_snr"] + (snr - s["snr"])

        out[key] = (round(max(RSSI_MIN, min(RSSI_MAX, rssi)), 1),
                    round(max(SNR_MIN, min(SNR_MAX, snr)), 1))
    return out


# --- main ---

def main():
    days, per_node, edge_min = 5, PER_NODE_DEFAULT, EDGE_MINUTES_DEFAULT
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    if "--per-node" in sys.argv:
        per_node = int(sys.argv[sys.argv.index("--per-node") + 1])
    if "--edge-min" in sys.argv:
        edge_min = int(sys.argv[sys.argv.index("--edge-min") + 1])

    scenario = load()
    db = MongoClient(DB_URI)[DB_NAME]

    seed(db, scenario, days, per_node, edge_min)

    total_edges = sum(len(i["links"]) for i in scenario["islands"])
    steps = (24 * 60) // edge_min
    print(f"\n[seed] done: {total_edges} edges x {steps} samples x {days} days "
          f"~= {total_edges * steps * days * 3} edge rows, plus node telemetry "
          f"and one route report per node per day.")
    print(f"[seed] reporter test: delete reporter/state/, run reporter.")


if __name__ == "__main__":
    main()