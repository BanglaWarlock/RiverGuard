"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

Minimal error logger: appends timestamped lines to logs/parser_errors.log.
Console output is removed for deployment. One write per call, append mode, reopened each
time: safe under the parser's per-message threads, and self-healing if
the file is deleted while running.
"""

import datetime
import os

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
LOG_FILE = os.path.join(LOG_DIR, "parser_errors.log")

def log_error(source, error):
    """Append one timestamped error line. Never raises."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.utcnow().isoformat()} [{source}] {error}\n")
    except Exception:
        pass   # logging must never be the thing that crashes the program