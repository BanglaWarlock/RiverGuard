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
    "database": None,
    "redis": None,
    "mqtt": None,
}

# Counters for the periodic [stats] line (stress testing).
# Incremented in mqtt_handlers, reported by main's stats thread.
message_count = 0