"""
RiverGuard database reset script.

Deletes everything the parser has written so the next test run starts
from a clean, predictable state (fresh counters, empty collections).

What it clears (drops entirely):
  global_stats, villages, master_nodes, river_nodes, telemetry,
  alerts, events, program_logs, heartbeats (legacy)

Notes:
  - Redis needs no clearing: we only use pub/sub, which stores nothing.
  - Stop the parser BEFORE running this. If the parser keeps running
    while collections are dropped, its counters drift from the database.
    After clearing, start the parser again - it recreates the indexes
    and the global_stats document automatically on startup.

Usage:
  python clear_db.py          asks "are you sure?" first
  python clear_db.py --yes    no prompt (for scripts)
"""

import sys
import datetime
from pymongo import MongoClient

DB_URI = "mongodb+srv://test:test@banglacluster.ntnbhcq.mongodb.net/?appName=BanglaCluster"
DB_NAME = "RiverGuard"

# Every collection the system uses, plus the legacy heartbeats collection
# from the old combined-heartbeat version (drop is a no-op if missing).
# Remove "program_logs" from this list if you ever want to keep logs.
COLLECTIONS = [
    "global_stats",
    "villages",
    "master_nodes",
    "river_nodes",
    "telemetry",
    "alerts",
    "events",
    "program_logs",
    "heartbeats",   # legacy, pre-v2
]


def main():
    # 1. Connect
    client = MongoClient(DB_URI)
    db = client[DB_NAME]

    # 2. Show what is about to be deleted (document counts per collection)
    print(f"Connected to {DB_NAME}. Collections to clear:\n")
    total = 0
    for name in COLLECTIONS:
        count = db[name].count_documents({})
        total += count
        print(f"  {name:<15} {count:>6} document(s)")
    print(f"\nTotal: {total} document(s) in {len(COLLECTIONS)} collections.")

    if total == 0:
        print("Database is already empty - nothing to do.")
        client.close()
        return

    # 3. Confirm (skipped with --yes)
    if "--yes" not in sys.argv:
        answer = input("\nType 'yes' to permanently delete these: ")
        if answer.strip().lower() != "yes":
            print("Cancelled - nothing was deleted.")
            client.close()
            return

    # 4. Drop each collection
    for name in COLLECTIONS:
        db[name].drop()
        print(f"  dropped {name}")

    # 5. Fresh zeroed global_stats, so /stats never 404s or returns {}
    #    between the clear and the next parser start (the parser resyncs
    #    these numbers itself on startup anyway).
    db.global_stats.insert_one({
        "_id": "global",
        "masters_online": 0,
        "masters_offline": 0,
        "river_nodes_online": 0,
        "river_nodes_offline": 0,
        "updated_at": datetime.datetime.utcnow(),
    })

    print("\nDone. Database is clean.")
    print("Reminder: if the parser was running, restart it now.")
    client.close()


if __name__ == "__main__":
    main()