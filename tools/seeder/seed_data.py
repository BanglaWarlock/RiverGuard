"""
Demo scenario GENERATOR - produces internally-consistent history.

Two islands (separate meshes, each with its own station):
  Island A: 89ABCDEF station + F1E2D3C4 (core), 0123ABCD,
           44556677 (edge, fair link), AABBCCDD (struggler, SF climbs)
  Island B: B24D6810 station + C3F59A21 (healthy), D7E81B42 (quiet one
           - goes silent after day 2)

Consistency rules the generator maintains:
  - packet/byte counters accumulate day to day (never decrease)
  - uptime grows with days (+ slight jitter)
  - sequence numbers increment per message
  - AABBCCDD's SF climbs 9 -> 12 (degrading link story)
  - blacklists: island A evolves (quarantine day 2, extend day 3,
    clear day 5); island B has none
  - DEADBEEF-style quiet node replaced by D7E81B42 (island B)

Everything is generated relative to 'now' so the story is always fresh.
"""

import datetime

ISLAND_A = {
    "station": "89ABCDEF",
    "nodes": ["F1E2D3C4", "0123ABCD", "44556677", "AABBCCDD"],
    "quiet": None,
}
ISLAND_B = {
    "station": "B24D6810",
    "nodes": ["C3F59A21", "D7E81B42"],
    "quiet": "D7E81B42",     # goes silent after day 2
}

SF_CLIMB = {"AABBCCDD": {1: 9, 2: 10, 3: 11, 4: 12, 5: 12, 6: 12, 7: 12}}
BASE_RSSI = {"F1E2D3C4": -58, "0123ABCD": -68, "44556677": -76, "AABBCCDD": -84,
             "C3F59A21": -61, "D7E81B42": -70}

def island_a_routes():
    """Island A's route table - fixed topology (deterministic)."""
    return [
        ("F1E2D3C4", {"r": [
            {"d": "89ABCDEF", "n": "89ABCDEF", "h": 1, "c": 1.1, "l": 1.1, "ri": -58, "sn": 11.2, "p": "F1E2D3C4>89ABCDEF", "a": 400},
            {"d": "0123ABCD", "n": "0123ABCD", "h": 1, "c": 1.3, "l": 1.3, "ri": -64, "sn": 9.8, "p": "F1E2D3C4>0123ABCD", "a": 900},
            {"d": "44556677", "n": "0123ABCD", "h": 2, "c": 3.1, "l": 1.3, "ri": -64, "sn": 9.8, "p": "F1E2D3C4>0123ABCD>44556677", "a": 1400},
            {"d": "AABBCCDD", "n": "0123ABCD", "h": 2, "c": 4.2, "l": 1.3, "ri": -64, "sn": 9.8, "p": "F1E2D3C4>0123ABCD>AABBCCDD", "a": 1600}]}),
        ("0123ABCD", {"r": [
            {"d": "89ABCDEF", "n": "F1E2D3C4", "h": 2, "c": 2.4, "l": 1.3, "ri": -64, "sn": 9.8, "p": "0123ABCD>F1E2D3C4>89ABCDEF", "a": 1800},
            {"d": "F1E2D3C4", "n": "F1E2D3C4", "h": 1, "c": 1.3, "l": 1.3, "ri": -64, "sn": 9.8, "p": "0123ABCD>F1E2D3C4", "a": 1200},
            {"d": "44556677", "n": "44556677", "h": 1, "c": 1.8, "l": 1.8, "ri": -76, "sn": 7.6, "p": "0123ABCD>44556677", "a": 600},
            {"d": "AABBCCDD", "n": "AABBCCDD", "h": 1, "c": 2.9, "l": 2.9, "ri": -84, "sn": 4.4, "p": "0123ABCD>AABBCCDD", "a": 500}]}),
        ("44556677", {"r": [
            {"d": "89ABCDEF", "n": "0123ABCD", "h": 3, "c": 4.2, "l": 1.8, "ri": -76, "sn": 7.6, "p": "44556677>0123ABCD>F1E2D3C4>89ABCDEF", "a": 2200},
            {"d": "0123ABCD", "n": "0123ABCD", "h": 1, "c": 1.8, "l": 1.8, "ri": -76, "sn": 7.6, "p": "44556677>0123ABCD", "a": 1100}]}),
        ("AABBCCDD", {"r": [
            {"d": "89ABCDEF", "n": "0123ABCD", "h": 3, "c": 5.1, "l": 2.9, "ri": -84, "sn": 4.4, "p": "AABBCCDD>0123ABCD>F1E2D3C4>89ABCDEF", "a": 3000},
            {"d": "0123ABCD", "n": "0123ABCD", "h": 1, "c": 2.9, "l": 2.9, "ri": -84, "sn": 4.4, "p": "AABBCCDD>0123ABCD", "a": 1500}]}),
        ("89ABCDEF", {"r": [
            {"d": "F1E2D3C4", "n": "F1E2D3C4", "h": 1, "c": 1.1, "l": 1.1, "ri": -58, "sn": 11.2, "p": "89ABCDEF>F1E2D3C4", "a": 700}]}),
    ]

def island_b_routes():
    return [
        ("C3F59A21", {"r": [
            {"d": "B24D6810", "n": "B24D6810", "h": 1, "c": 1.2, "l": 1.2, "ri": -61, "sn": 10.5, "p": "C3F59A21>B24D6810", "a": 500},
            {"d": "D7E81B42", "n": "D7E81B42", "h": 1, "c": 1.6, "l": 1.6, "ri": -70, "sn": 8.2, "p": "C3F59A21>D7E81B42", "a": 800}]}),
        ("D7E81B42", {"r": [
            {"d": "B24D6810", "n": "C3F59A21", "h": 2, "c": 2.8, "l": 1.6, "ri": -70, "sn": 8.2, "p": "D7E81B42>C3F59A21>B24D6810", "a": 1900}]}),
        ("B24D6810", {"r": [
            {"d": "C3F59A21", "n": "C3F59A21", "h": 1, "c": 1.2, "l": 1.2, "ri": -61, "sn": 10.5, "p": "B24D6810>C3F59A21", "a": 600}]}),
    ]

BLACKLIST_TIMELINE = {
    # day -> policy (island A only; v2 format with reason from day 3)
    2: {"v": 1, "sequence": 5, "edges": [["0123ABCD", "AABBCCDD"]]},
    3: {"v": 1, "sequence": 6, "edges": [["0123ABCD", "AABBCCDD"], ["44556677", "89ABCDEF"]]},
    5: {"v": 2, "sequence": 7, "edges": [["0123ABCD", "AABBCCDD"]], "reason": "link_quality"},
}


def generate(days=5, per_day=10):
    """The full history: telemetry + route reports + blacklists, each
    entry (kind, node_id, payload, day_offset) - day_offset 0 = today,
    days-1 = oldest. Counters/uptime/sequence accumulate consistently."""
    import random
    random.seed(42)   # deterministic: same seed data every run

    telemetry, routes, blacklists = [], [], []
    counters = {}
    seqs = {}
    t = 0  # message sequence shared per node

    all_nodes = ([(n, ISLAND_A) for n in ISLAND_A["nodes"]] +
                 [(n, ISLAND_B) for n in ISLAND_B["nodes"]])

    # node/station -> island, built once (stations included - they
    # have routes too)
    island_of = {}
    for island in (ISLAND_A, ISLAND_B):
        for n in island["nodes"] + [island["station"]]:
            island_of[n] = island

    for day in range(days, 0, -1):           # oldest first
        for i in range(per_day):
            for node_id, island in all_nodes:
                # quiet node: island B's D7E81B42 stops after day 3
                if island["quiet"] == node_id and day <= 2:
                    continue
                c = counters.setdefault(node_id,
                    {"tx": random.randint(20, 60), "rx": 0,
                     "txb": random.randint(800, 2400), "rxb": 0,
                     "up": random.randint(30, 90)})
                tx = random.randint(6, 14)
                rx = int(tx * random.uniform(0.82, 0.99))
                c["tx"] += tx; c["rx"] += rx
                c["txb"] += tx * 41; c["rxb"] += int(tx * 39)
                c["up"] += 24 * 60 // per_day + random.randint(-5, 5)

                sf = SF_CLIMB.get(node_id, {}).get(day, 7)

                t += 1
                telemetry.append((node_id, {
                    "node": node_id, "uptime_minute": c["up"],
                    "sequence": seqs.get(node_id, 0) + 1, "tx_packets": c["tx"],
                    "rx_packets": c["rx"], "tx_bytes": c["txb"],
                    "rx_bytes": c["rxb"], "sf": sf}, day))
                seqs[node_id] = seqs.get(node_id, 0) + 1

        # one route report per node per day
        rtable = island_a_routes() + island_b_routes()
        for node_id, payload in rtable:
            island = island_of[node_id]
            if island["quiet"] == node_id and day <= 2:
                continue
            p = dict(payload)
            p["s"] = (days - day + 1) * 10 + 3
            p["g"] = (days - day + 1) * 14400000
            # jitter the RSSIs per report
            for rt in p["r"]:
                if rt.get("ri") is not None:
                    rt["ri"] += random.randint(-3, 3)
                    rt["sn"] = round(max(3.0, rt["sn"] - random.uniform(0, 1.5)), 1)
            routes.append((node_id, p, day))

    for day, bl in BLACKLIST_TIMELINE.items():
        if day <= days:
            blacklists.append((None, {**bl}, day))

    return telemetry, routes, blacklists