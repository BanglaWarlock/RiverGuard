"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

Shared machinery for every stress-test tool:
  - device_info():      what machine the test ran on (goes in the report)
  - find_services():    locate parser/api/simulator processes
  - MetricsThread:      samples RAM/CPU/threads every second into CSV,
                        AND acts as the safety watchdog: if any service
                        exceeds the RAM limit, the whole run stops
                        (cleanly - partial data is still reported).
  - stop_event + abort_reason: every tool checks the same stop flag.
"""

import csv
import datetime
import os
import platform
import subprocess
import threading
import time

import psutil

# Services we look for by command line. Spawn the parser/api/simulator
# BEFORE starting any tool that uses find_services().
SERVICE_MATCHES = {
    "parser": os.path.join("parser", "main.py"),
    "api":    os.path.join("api", "main.py"),
}

stop_event = threading.Event()
abort_reason = None      # set by the watchdog; stamped on the report

"""Ask everything to stop. Used by Ctrl+C and the RAM watchdog."""
def request_stop(reason):
    global abort_reason
    if not stop_event.is_set():
        abort_reason = reason
    stop_event.set()

"""Snapshot of the test machine - the 'environment' section of the report."""
def device_info():
    vm = psutil.virtual_memory()
    info = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "processor": platform.processor() or "unknown",
        "cpu_cores_physical": psutil.cpu_count(logical=False),
        "cpu_cores_logical": psutil.cpu_count(logical=True),
        "ram_total_mb": round(vm.total / 1e6, 0),
        "ram_available_mb": round(vm.available / 1e6, 0),
        "python": platform.python_version(),
    }
    return info


"""Locate the parser and API processes by their command lines."""
def find_services():
    found = {}
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(p.info["cmdline"] or []).replace("/", os.sep)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        for label, fragment in SERVICE_MATCHES.items():
            # normalize slashes so it works on Windows and Linux
            if fragment in cmd and label not in found:
                try:
                    found[label] = psutil.Process(p.info["pid"])
                except psutil.NoSuchProcess:
                    pass
    return found


def docker_mem_mb():
    """{container: memory MB} via docker stats (empty if docker is down)."""
    try:
        out = subprocess.run(
            ["docker", "stats", "--no-stream", "--format",
             "{{.Name}}|{{.MemUsage}}"],
            capture_output=True, text=True, timeout=3).stdout
        result = {}
        for line in out.strip().splitlines():
            parts = line.split("|")
            if len(parts) != 2:
                continue
            value = parts[1].split("/")[0].strip()
            try:
                if value.endswith("GiB"):   mb = float(value[:-3]) * 1024
                elif value.endswith("MiB"): mb = float(value[:-3])
                elif value.endswith("KiB"): mb = float(value[:-3]) / 1024
                elif value.endswith("B"):   mb = float(value[:-1]) / 1e6
                else: continue
            except ValueError:
                continue
            result[parts[0]] = round(mb, 1)
        return result
    except Exception:
        return {}


class MetricsThread(threading.Thread):
    """
    Samples every service's RAM/CPU/threads + docker container memory once
    per second, writes one CSV row, and watches the RAM limit.

    The watchdog rule: if ANY service exceeds ram_limit_mb, the whole
    run stops - but cleanly: stop_event is set, partial CSV stands, the
    report still gets built, and the abort reason is stamped on it.
    """

    def __init__(self, csv_path, ram_limit_mb=512):
        super().__init__(daemon=True)
        self.csv_path = csv_path
        self.ram_limit_mb = ram_limit_mb
        self.services = find_services()
        for p in self.services.values():
            p.cpu_percent()   # prime the CPU counters (first call is 0)

    def run(self):
        fields = ["seconds"] + \
            [f"{s}_rss_mb" for s in self.services] + \
            [f"{s}_cpu_pct" for s in self.services] + \
            [f"{s}_threads" for s in self.services] + \
            ["docker_redis_mb"]
        started = time.monotonic()

        with open(self.csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()

            while not stop_event.is_set():
                row = {"seconds": round(time.monotonic() - started, 1)}
                breached = None

                for name, proc in self.services.items():
                    try:
                        rss = proc.memory_info().rss / 1e6
                        row[f"{name}_rss_mb"] = round(rss, 1)
                        row[f"{name}_cpu_pct"] = proc.cpu_percent()
                        row[f"{name}_threads"] = proc.num_threads()
                        if rss > self.ram_limit_mb:
                            breached = f"{name} exceeded {self.ram_limit_mb}MB ({rss:.0f}MB)"
                    except psutil.NoSuchProcess:
                        row[f"{name}_rss_mb"] = None   # service stopped

                row["docker_redis_mb"] = docker_mem_mb().get("redis")

                writer.writerow(row)
                f.flush()   # data survives even a hard kill

                if breached:
                    request_stop(f"RAM WATCHDOG: {breached}")
                    break

                time.sleep(1.0)