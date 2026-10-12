"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

Minimal error logger: appends timestamped lines to logs/api_errors.log.
Console output removed for deployment - this file is what remains.
"""

import datetime
import os

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
LOG_FILE = os.path.join(LOG_DIR, "api_errors.log")

def log_error(source, error):
    """Append one timestamped error line. Never raises."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.utcnow().isoformat()} [{source}] {error}\n")
    except Exception:
        pass