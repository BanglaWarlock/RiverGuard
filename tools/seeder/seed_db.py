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

def seed(db, scenario, days, per_node, edge_min):
    """The ONE orchestration path (main calls this and nothing else)."""
    timeline = [e for e in scenario.get("blacklist_timeline", [])
                if e["day"] <= days]

    for island in scenario["islands"]:
        # 1. dense edge series (writes telemetry; returns the history
        #    so route reports use the SAME numbers that were stored)
        edge_history = seed_edge_telemetry(db, island, days, edge_min)

        # 2. sparse node telemetry (parser-shaped payloads)
        seed_node_telemetry(db, island, days, per_node)

        # 3. routes: one per node per day, from the day's final samples
        seed_routes(db, island, days, edge_history, timeline)

        # 4. mesh_nodes: final snapshots
        seed_mesh_nodes(db, island, edge_history)
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


def seed_routes(db, island, days, edge_history, timeline):
    """
    ONE route report per node per day, computed from the day's FINAL
    directional samples. Routing convention (NODE-KNOWLEDGE MODEL):
    the cost of a hop X -> Y is X's own measurement of Y - each node
    routes on what it hears, and the report's first-hop ri/sn is the
    node's own view of its next hop. (True-delivery model - cost X -> Y
    is Y's view of X - is the one-line alternative noted below.)
    """
    for day in range(days, 0, -1):
        last = edge_history[day]
        banned = {frozenset(e) for e in blacklist_on(timeline, day)}

        # DIRECTIONAL adjacency: adj[x] holds x's view of each neighbor
        adj = {}
        for l in island["links"]:
            if frozenset((l["a"], l["b"])) in banned:
                continue
            a, b = l["a"], l["b"]
            rssi_a, snr_a, cost_a = last[f"{a}>{b}"]   # a's view of b
            rssi_b, snr_b, cost_b = last[f"{b}>{a}"]   # b's view of a
            adj.setdefault(a, []).append((b, cost_a, rssi_a, snr_a))
            adj.setdefault(b, []).append((a, cost_b, rssi_b, snr_b))
            # true-delivery model instead:
            #   adj[a].append((b, cost_b, ...)) - hop a->b costed by
            #   how b hears a - swap the cost/quality tuples above.

        for node_id in island["nodes"] + [island["station"]]:
            routes = dijkstra(adj, node_id)   # works on directed adj
            table = []
            for dest, info in routes.items():
                first_hop = info["next_hop"]
                # the node's OWN view of its next hop (matches adj above)
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
            db.route_reports.insert_one({
                "node_id": node_id,
                "payload": {
                    "s": (days - day + 1) * 10 + 3,
                    "g": (days - day + 1) * 14400000,
                    "r": table,
                },
                "timestamp": ts_in_day(day, 24 * 60 - 1),
            })


def seed_mesh_nodes(db, island, edge_history):
    """Final mesh_nodes snapshots: same field set the parser writes."""
    last = edge_history[1]
    node_ids = island["nodes"] + [island["station"]]

    neighbors = {nid: [] for nid in node_ids}
    for l in island["links"]:
        neighbors[l["a"]].append(l["b"])
        neighbors[l["b"]].append(l["a"])

    for node_id in node_ids:
        # first-hop quality: one of THIS node's own edges (not the
        # island's first link - the old code read the wrong edge and
        # most nodes got None)
        link = next((l for l in island["links"]
                     if l["a"] == node_id or l["b"] == node_id), None)
        rssi = snr = None
        if link:
            other = link["b"] if link["a"] == node_id else link["a"]
            rssi, snr, _ = last[f"{node_id}>{other}"]   # node's own view

        db.mesh_nodes.update_one(
            {"node_id": node_id},
            {"$set": {
                "last_seen": ts_in_day(1, 24 * 60 - 1),   # = route report ts
                "link_count": len(neighbors[node_id]),
                "first_hop_rssi": rssi, "first_hop_snr": snr,
                "topology_seq": 10 * len(edge_history) + 3,  # = day-1 route "s"
            },
             "$setOnInsert": {"node_id": node_id,
                              "first_seen": day_start(len(edge_history))}},
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