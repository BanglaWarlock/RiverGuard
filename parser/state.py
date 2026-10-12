"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

Shared runtime state to share data to other files.

main.py sets up the connections and fills in the state dictionary.
Other files can read from the state dictionary to access the database, MQTT, and Redis connections.
"""

import threading

# Set by main() when Ctrl+C / SIGTERM arrives; the wait loop in main watches it
stop_event = threading.Event()

state = {
    "db": None,               # the database handle (database_helper reads this)
    "database_client": None,   # the MongoClient (cleanup closes this)
    "redis": None,            # None = Redis down, parser continues
}