"""
Insert GENERATED demo history directly into the database.
Two islands, days of consistent telemetry, evolving blacklist.

Usage:
  python seed_db.py                      # 5 days, 10 messages/node/day
  python seed_db.py --days 3             # shorter history
  python seed_db.py --per-day 20         # denser (bigger reporter CSVs)
  python seed_db.py --days 5 --per-day 12
"""

import datetime
import sys
from pymongo import MongoClient
from seed_data import generate, ISLAND_A, ISLAND_B
import random


DB_URI, DB_NAME = "mongodb://localhost:27017", "RiverGuard"

def main():
    days, per_day = 5, 10
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    if "--per-day" in sys.argv:
        per_day = int(sys.argv[sys.argv.index("--per-day") + 1])

    telemetry, routes, blacklists = generate(days, per_day)
    db = MongoClient(DB_URI)[DB_NAME]
    now = datetime.datetime.utcnow()

    def ts_for(day, hour=None):
        """Timestamp for day N (1=today, 2=yesterday...), at a random-ish hour."""
        hour = hour if hour is not None else random.randint(1, 22)
        base = now - datetime.timedelta(days=day - 1)
        return base.replace(hour=hour, minute=random.randint(0, 59))

    for node_id, payload, day in telemetry:
        db.telemetry.insert_one({"node_id": node_id, "payload": payload,
                                  "timestamp": ts_for(day)})
    for node_id, payload, day in routes:
        db.route_reports.insert_one({"node_id": node_id, "payload": payload,
                                      "timestamp": ts_for(day, random.randint(0, 20))})

    # blacklist timeline: day's version stored at that day's time
    for _, bl, day in blacklists:
        db.blacklists.insert_one({**bl, "timestamp": ts_for(day)})
    # current = the latest day's policy (or none if timeline is empty)
    if blacklists:
        latest = max(blacklists, key=lambda b: b[1]["sequence"])[1]
        db.current_blacklist.update_one({"_id": "active"},
            {"$set": {**latest, "received": ts_for(1)}}, upsert=True)

    # mesh_nodes: current state from the LAST telemetry/route per node
    for node_id, payload, day in telemetry:
        if day != 1: continue    # only today's rows build current state
        db.mesh_nodes.update_one(
            {"node_id": node_id},
            {"$set": {"last_seen": ts_for(1),
                      **{k: payload[k] for k in
                         ("uptime_minute", "sf", "tx_packets", "rx_packets",
                          "tx_bytes", "rx_bytes", "sequence")}},
             "$setOnInsert": {"node_id": node_id,
                              "first_seen": ts_for(days)}},
            upsert=True)
    # rename the seq key to match the parser's storage (known, accepted gap)
    # (telemetry_seq is not set here - documented in the folder notes)

    for node_id, payload, day in routes:
        if day != 1: continue
        routes_r = payload.get("r", [])
        fh = next((r for r in routes_r if r.get("ri") is not None), None)
        db.mesh_nodes.update_one(
            {"node_id": node_id},
            {"$set": {"last_seen": ts_for(1),
                      "topology_seq": payload.get("s"),
                      "link_count": len(routes_r),
                      "first_hop_rssi": fh["ri"] if fh else None,
                      "first_hop_snr": fh["sn"] if fh else None}},
            upsert=True)

    print(f"Seeded: {len(telemetry)} telemetry, {len(routes)} routes, "
          f"{len(blacklists)} blacklists across {days} days, 2 islands.")
    print(f"Reporter test: delete reporter/state/, run reporter -> "
          f"{min(days, 7)} dated emails.")

if __name__ == "__main__":
    main()