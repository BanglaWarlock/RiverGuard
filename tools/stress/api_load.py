"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

API load generator: simulates many website users.

Two kinds of traffic at once:
  - REST: N threads hammering GET /stats, /villages, /villages/X/nodes
          (the calls the real website makes on every page load/refresh)
  - SSE : M connections holding /stream open, counting events received
          (the real website's live stream)

Writes one CSV row per REST request (latency ms) and prints a summary.
Runnable standalone (python api_load.py --duration 60) or imported by
run_stress.py.
"""

import argparse
import csv
import datetime
import json
import statistics
import threading
import time
import urllib.request

import requests

import test_common 
from test_common import stop_event, request_stop

API = "http://127.0.0.1:8000"


class RestWorker(threading.Thread):
    """One simulated user: loops the website's page-load calls."""

    def __init__(self, csv_path, lock):
        super().__init__(daemon=True)
        self.csv_path, self.lock = csv_path, lock
        self.count = 0

    def run(self):
        paths = ["/stats", "/villages",
                 "/villages/SUTS/nodes", "/alerts?limit=50"]
        while not stop_event.is_set():
            for path in paths:
                if stop_event.is_set():
                    return
                t0 = time.perf_counter()
                try:
                    r = requests.get(API + path, timeout=10)
                    ok = r.status_code == 200
                except Exception:
                    ok = False
                ms = (time.perf_counter() - t0) * 1000
                self.count += 1
                with self.lock, open(self.csv_path, "a", newline="") as f:
                    csv.writer(f).writerow(
                        [datetime.datetime.now().isoformat(timespec="seconds"),
                         path, round(ms, 1), ok])


class SseWorker(threading.Thread):
    """One simulated browser: holds the stream open, counts events."""

    def __init__(self):
        super().__init__(daemon=True)
        self.events = 0

    def run(self):
        try:
            r = requests.get(API + "/stream", stream=True, timeout=None)
            for line in r.iter_lines(decode_unicode=True):
                if stop_event.is_set():
                    break
                if line and line.startswith("data:"):
                    self.events += 1
        except Exception:
            pass   # stream ended (server stopped / watchdog)


def run_load(csv_path, duration_s, rest_users, sse_users):
    """Run the load for duration_s. Returns a summary dict."""

    lock = threading.Lock()
    with open(csv_path, "w", newline="") as f:
        csv.writer(f).writerow(["time", "path", "latency_ms", "ok"])

    workers = [RestWorker(csv_path, lock) for _ in range(rest_users)]
    streams = [SseWorker() for _ in range(sse_users)]
    for w in workers + streams:
        w.start()

    t0 = time.monotonic()
    while not stop_event.is_set() and time.monotonic() - t0 < duration_s:
        time.sleep(1.0)

    request_stop("api_load duration elapsed")   # only ends ITS OWN run
    stop_event.clear()                          # (the orchestrator reuses it)
    for w in workers:
        w.join(timeout=2)

    # read back latencies for percentiles
    lats, oks = [], 0
    with open(csv_path) as f:
        next(f)
        for row in csv.reader(f):
            lats.append(float(row[2]))
            oks += row[3] == "True"

    def pct(p):
        s = sorted(lats)
        return round(s[min(int(len(s) * p), len(s) - 1)], 1) if s else None

    elapsed = time.monotonic() - t0
    return {
        "rest_requests": len(lats),
        "rest_ok": oks,
        "rest_per_s": round(len(lats) / elapsed, 1) if elapsed else 0,
        "rest_avg_ms": round(statistics.mean(lats), 1) if lats else None,
        "rest_p95_ms": pct(0.95),
        "rest_max_ms": round(max(lats), 1) if lats else None,
        "sse_users": sse_users,
        "sse_events_total": sum(s.events for s in streams),
        "sse_events_per_s_per_user": round(
            sum(s.events for s in streams) / elapsed / max(sse_users, 1), 1),
        "duration_s": round(elapsed, 1),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=int, default=60)
    ap.add_argument("--rest", type=int, default=10)
    ap.add_argument("--sse", type=int, default=5)
    ap.add_argument("--out", default="api_load.csv")
    a = ap.parse_args()

    import test_common
    print(run_load(a.out, a.duration, a.rest, a.sse))