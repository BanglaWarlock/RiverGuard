"""
RiverGuard database reset - drops the ENTIRE RiverGuard database.

Stops the parser first (no mid-clear writes; it recreates the indexes
on restart), drops the database, unsets the broker's retained
blacklist (or the old policy resurrects when the parser resubscribes),
then restarts the parser.

The API is NOT restarted - it reads the database per-request, so the
website shows the empty state on its next refresh automatically.

Usage: python clear_db.py          (asks 'yes' first)
       python clear_db.py --yes    (no prompt - for scripts/bats)
"""

import subprocess
import sys

from pymongo import MongoClient

DB_URI = "mongodb://localhost:27017"
DB_NAME = "RiverGuard"

PARSER_CONTAINER = "riverguard-parser"
BROKER_CONTAINER = "riverguard-eclipse"
BLACKLIST_TOPIC = "mesh/control/blacklist"


def docker(*args):
    """Run a docker command quietly; returns True/False."""
    r = subprocess.run(["docker", *args], capture_output=True, text=True)
    return r.returncode == 0


def container_running(name):
    r = subprocess.run(
        ["docker", "ps", "--filter", f"name={name}",
         "--filter", "status=running", "--format", "{{.Names}}"],
        capture_output=True, text=True)
    return name in r.stdout


def clear_retained_blacklist():
    """Unset the retained blacklist on the broker.

    mosquitto_pub -r -n publishes a NULL payload with the retain flag -
    per the MQTT spec this removes the retained message, so the
    restarted parser gets nothing on resubscribe. Runs inside the
    broker container, so no host-side MQTT tools are needed.
    """
    r = subprocess.run(
        ["docker", "exec", BROKER_CONTAINER, "mosquitto_pub",
         "-t", BLACKLIST_TOPIC, "-r", "-n"],
        capture_output=True, text=True)
    return r.returncode == 0


def main():
    client = MongoClient(DB_URI)

    was_running = container_running(PARSER_CONTAINER)

    print(f"Dropping the ENTIRE database '{DB_NAME}'.")
    if was_running:
        print("(parser is running - it will be stopped and restarted)")
    if "--yes" not in sys.argv and input("Type 'yes' to confirm: ").strip() != "yes":
        print("Cancelled.")
        return

    # 1. stop the parser (no mid-clear writes; restart recreates indexes)
    if was_running:
        docker("stop", PARSER_CONTAINER)
        print(f"[clear] {PARSER_CONTAINER} stopped")

    # 2. drop the whole database (indexes included - the parser
    #    recreates them on startup)
    client.drop_database(DB_NAME)
    print(f"[clear] database '{DB_NAME}' dropped")

    # 3. unset the retained blacklist BEFORE the parser restarts, or
    #    the broker re-delivers it and the old policy comes back
    if container_running(BROKER_CONTAINER):
        if clear_retained_blacklist():
            print(f"[clear] retained blacklist unset on {BROKER_CONTAINER}")
        else:
            print(f"[clear] WARNING: could not unset the retained blacklist -")
            print(f"[clear] the old policy will return when the parser restarts.")
    else:
        print(f"[clear] note: broker not running - a retained blacklist (if any)")
        print(f"[clear] survives in mqtt/data and returns when it next starts.")

    # 4. restart the parser
    if was_running:
        docker("start", PARSER_CONTAINER)
        print(f"[clear] {PARSER_CONTAINER} restarted (indexes recreated)")

    print("[clear] done. Website: refresh to see the empty state.")


if __name__ == "__main__":
    main()