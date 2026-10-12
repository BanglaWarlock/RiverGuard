'''
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.
'''

import signal
from state import stop_event
import connections
import logger

def signal_handler(signum, frame):
    stop_event.set()

signal.signal(signal.SIGINT, signal_handler)    # Ctrl+C
signal.signal(signal.SIGTERM, signal_handler)   # Docker stop

def cleanup():
    connections.cleanup_mqtt()
    connections.cleanup_redis()
    connections.cleanup_database()

def main():
    try:
        # 1. Database is REQUIRED.
        if not connections.setup_database():
            return

        # 2. MQTT is REQUIRED.
        if not connections.setup_mqtt():
            cleanup()
            return

        # 3. Redis is OPTIONAL - parser continues database-only without it.
        connections.setup_redis()

        # 4. Wait for a stop signal. Everything else happens in the
        #    MQTT callback's threads.
        while not stop_event.is_set():
            stop_event.wait(timeout=1.0)

        # 5. Graceful shutdown
        cleanup()

    except Exception as e:
        logger.log_error("main", e)
        cleanup()

if __name__ == "__main__":
    main()