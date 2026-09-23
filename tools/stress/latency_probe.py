"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

End-to-end latency: MQTT publish -> broker -> parser -> Redis -> API -> SSE.

Method: publish a battery message whose VALUE is the send timestamp,
then watch the SSE stream until that exact timestamp comes back out.

Three timestamps give TWO segments plus the total:
  t0  publish time           (known by the probe)
  t1  parser "ts"            (already inside every Redis envelope!)
  t2  SSE arrival time       (known by the probe)
  t0->t1  ingest half:  broker + parser + Mongo write + Redis publish
  t1->t2  notify half:  Redis + API + SSE delivery
  t0->t2  the whole path (comparable to the FYP's ~9ms measurement)

All on one machine, so clock skew is zero and segments are trustworthy.
Runnable standalone or driven by run_stress.py.
"""

import csv
import json
import statistics
import time
import urllib.request

import paho.mqtt.client as mqtt

import test_common
from test_common import stop_event
from datetime import datetime, timezone

BROKER = "broker.emqx.io"
API = "http://127.0.0.1:8000"


def run_probe(csv_path, count=20, interval=1.0):
    """Publish `count` probes, one per interval. Returns a summary dict."""
    client = mqtt.Client()
    client.connect(BROKER, 1883, 60)
    client.loop_start()

    resp = urllib.request.urlopen(API + "/stream")
    rows = []

    for _ in range(count):
        if stop_event.is_set():
            break
        t0 = time.time()
        client.publish("riverguard/PROBE/battery/PROBE-1",
                       json.dumps({"value": t0}), qos=1)

        matched = False
        deadline = time.time() + 15
        while time.time() < deadline and not stop_event.is_set():
            line = resp.readline().decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("data: "):
                continue
            try:
                msg = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            if (msg.get("node_id") == "PROBE-1"
                    and msg.get("channel") == "battery"):
                bat = msg["data"].get("bat")
                if isinstance(bat, (int, float)) and abs(bat - t0) < 1.0:
                    t2 = time.time()
                    t1 = time.mktime(time.strptime(
                        msg["ts"], "%Y-%m-%dT%H:%M:%S.%f")) \
                        if "." in msg["ts"] else None
                    if t1 is None:   # ts came without microseconds
                        t1 = time.mktime(time.strptime(
                            msg["ts"].split(".")[0], "%Y-%m-%dT%H:%M:%S"))
                    rows.append({"t0": t0, "t1": t1, "t2": t2,
                                 "ingest_ms": (t1 - t0) * 1000,
                                 "notify_ms": (t2 - t1) * 1000,
                                 "total_ms": (t2 - t0) * 1000})
                    matched = True
                    break
        if not matched:
            rows.append({"t0": t0, "t1": None, "t2": None,
                         "ingest_ms": None, "notify_ms": None, "total_ms": None})
        time.sleep(interval)

    client.loop_stop()
    client.disconnect()

    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["t0", "t1", "t2", "ingest_ms",
                                          "notify_ms", "total_ms"])
        w.writeheader()
        w.writerows(rows)

    def stats(key):
        vals = sorted(r[key] for r in rows if r[key] is not None)
        if not vals:
            return None
        return {
            "avg": round(statistics.mean(vals), 1),
            "p95": round(vals[min(int(len(vals) * .95), len(vals) - 1)], 1),
            "max": round(max(vals), 1),
        }

    return {"probes": len(rows), "ok": sum(1 for r in rows if r["total_ms"]),
            "ingest_ms": stats("ingest_ms"),
            "notify_ms": stats("notify_ms"),
            "total_ms": stats("total_ms")}