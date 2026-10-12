"""
RiverGuard database reset - drops all collections in the local database.

Convenience: stops the parser first (so it doesn't write mid-clear and
recreate indexes mid-drop), clears, then restarts it. The API is NOT
restarted - it reads the database per-request, so the website shows the
cleared state on its next refresh automatically.

Usage: python clear_db.py          (asks 'yes' first)
       python clear_db.py --yes    (no prompt - for scripts/bats)
"""

import subprocess
import sys
from pymongo import MongoClient

DB_URI = "mongodb://localhost:27017"
DB_NAME = "RiverGuard"

COLLECTIONS = ["mesh_nodes", "telemetry", "route_reports",
               "blacklists", "current_blacklist"]

PARSER_CONTAINER = "riverguard-parser"

def docker(*args):
    """Run a docker command quietly; returns True/False."""
    r = subprocess.run(["docker", *args], capture_output=True, text=True)
    return r.returncode == 0

def parser_running():
    r = subprocess.run(
        ["docker", "ps", "--filter", f"name={PARSER_CONTAINER}",
         "--filter", "status=running", "--format", "{{.Names}}"],
        capture_output=True, text=True)
    return PARSER_CONTAINER in r.stdout

def main():
    db = MongoClient(DB_URI)[DB_NAME]

    total = sum(db[c].count_documents({}) for c in COLLECTIONS)
    if total == 0 and not parser_running():
        print("Already empty, parser not running - nothing to do.")
        return

    was_running = parser_running()

    print(f"Clearing {total} document(s) from {len(COLLECTIONS)} collections.")
    if was_running:
        print(f"(parser is running - it will be stopped and restarted)")
    if "--yes" not in sys.argv and input("Type 'yes' to confirm: ").strip() != "yes":
        print("Cancelled.")
        return

    # 1. stop the parser (no mid-clear writes, no index recreation races)
    if was_running:
        docker("stop", PARSER_CONTAINER)
        print(f"[clear] {PARSER_CONTAINER} stopped")

    # 2. drop
    for c in COLLECTIONS:
        db[c].drop()
    print(f"[clear] {total} document(s) dropped")

    # 3. restart the parser - it recreates indexes on startup
    if was_running:
        docker("start", PARSER_CONTAINER)
        print(f"[clear] {PARSER_CONTAINER} restarted (indexes recreated on startup)")

    print("[clear] done. Website: refresh to see the empty state.")

if __name__ == "__main__":
    main()