'''
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.
'''

# Start the program by running this file.
# Connect to the database, MQTT broker, and Redis, then wait for a stop
# signal (Ctrl+C, or SIGTERM from Docker) and shut down gracefully.

import signal
import time
import state
from state import stop_event
import connections
import threading

# Keep track of message count and time for the messages
last_stats = {"t": time.monotonic(), "n": 0}

# Set stop event on termination signals to allow for graceful shutdown
def signal_handler(signum, frame):
    stop_event.set()


# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)    # Ctrl+C
signal.signal(signal.SIGTERM, signal_handler)   # Docker stop / kill

"""Close everything that is open. Order matters: MQTT first (stop the
incoming flow), then the rest. All are safe to call unconditionally."""
def cleanup():
    connections.cleanup_mqtt()
    connections.cleanup_redis()
    connections.cleanup_database()


def main():
    try:
        # 1. Database is REQUIRED - no database, no point running.
        if not connections.setup_database():
            print("Database setup failed, shutting down...")
            return

        # 2. MQTT is REQUIRED - it is the entire input of this program.
        if not connections.setup_mqtt():
            print("MQTT setup failed, shutting down...")
            cleanup()
            return

        # 3. Redis is OPTIONAL - setup_redis returns True even when it's down;
        #    the program continues, database-only, no real-time notifications.
        connections.setup_redis()

        print("\n[parser] Running. Ctrl+C to stop.\n")

        # 4. Keep looping as long as our stop flag is not set.
        #    Everything else happens in the MQTT callback's threads.
        # Keeps track of total messages handled
        while not stop_event.is_set():
            stop_event.wait(timeout=1.0)
            now = time.monotonic()
            if now - last_stats["t"] >= 30:
                rate = (state.message_count - last_stats["n"]) / (now - last_stats["t"])
                print(f"[stats] total {state.message_count}, {rate:.1f} msgs/s, "
                    f"threads={threading.active_count()}")
                last_stats.update(t=now, n=state.message_count)

        # 5. Graceful shutdown
        print("\n[parser] Shutting down gracefully...")
        cleanup()
        print("[parser] Done.")

    except Exception as e:
        print(f"\n[parser] Unexpected error occurred: {e}")
        print("\n[parser] Shutting down gracefully...")
        cleanup()
        print("[parser] Done.")


if __name__ == "__main__":
    main()