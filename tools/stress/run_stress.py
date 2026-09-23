"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

THE entry point for stress testing. Run this file; it runs everything else.

  python run_stress.py                    full scenario matrix (A,B,C,D)
  python run_stress.py --scenario B       just one scenario
  python run_stress.py --duration 120     shorter/longer scenarios
  python run_stress.py --ram-limit 400    tighten the watchdog

Prerequisites (the orchestrator checks and refuses otherwise):
  - parser running      (python parser/main.py)
  - API running         (python api/main.py)  - checked via GET /health
  - Redis running       (warned, not required - but /stream needs it)
The simulator is spawned BY this script (it is test equipment, not the
system under test) and killed at the end of each scenario.

Scenarios:
  A  baseline    : no simulator, no load       -> the idle floor (threads,
                   RAM) that later numbers are compared against
  B  high parse  : stress simulator only        -> does parsing degrade reads?
  C  high api    : normal simulator + api_load  -> API throughput ceiling
  D  both        : stress simulator + api_load  -> flood event: heavy
                   telemetry AND many worried users refreshing

Each scenario: metrics CSV + api-load CSV + latency probes, all into
tools/stress/results/run_<timestamp>/. Ctrl+C ends gracefully and the
report is still built from whatever was collected.
"""

import argparse
import json
import os
import signal
import subprocess
import time
import urllib.request

import test_common
from test_common import stop_event, request_stop
import api_load
import latency_probe
from report_builder import build_report

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
BROKER = os.getenv("MQTT_BROKER", "broker.emqx.io")
API = "http://127.0.0.1:8000"

SCENARIOS = {
    "A": {"sim": None,        "load": False, "duration": 60},
    "B": {"sim": "stress",    "load": False, "duration": 180},
    "C": {"sim": "normal",    "load": True,  "duration": 180},
    "D": {"sim": "stress",    "load": True,  "duration": 180},
    # E : escalation ladder - climbs ~100 to ~6000 msg/s over ~8 minutes,
    #     holds after saturation.
    "E": {"sim": "escalate",  "load": False, "duration": 600},
    # F : unpaced ceiling - rate = whatever the generator can produce.
    "F": {"sim": "unpaced",   "load": False, "duration": 300},
}

def spawn_sim(kind):
    """Start the simulator as a subprocess. Returns the Popen."""
    script = "stress_sim.py" if kind in ("stress", "escalate", "unpaced") else "simulator.py"
    path = os.path.join(ROOT, "simulator", script)
    env = dict(os.environ, MQTT_BROKER=BROKER, VERBOSE="0")
    if kind == "escalate":
        env["ESCALATE"] = "1"
    if kind == "unpaced":
        env["UNPACED"] = "1"
    return subprocess.Popen(["python", path], cwd=os.path.dirname(path), env=env)


def preflight():
    """Refuse to start a broken test run."""
    services = test_common.find_services()
    missing = [s for s in ("parser", "api") if s not in services]
    if missing:
        print(f"PREFLIGHT FAILED: {missing} not running - start them first.")
        print("  parser: python parser/main.py")
        print("  api:    python api/main.py")
        return False
    try:
        urllib.request.urlopen(API + "/health", timeout=5).read()
    except Exception as e:
        print(f"PREFLIGHT FAILED: API /health not answering: {e}")
        return False
    print("[preflight] parser + API up and answering")
    return True


def run_scenario(name, cfg, out_dir, duration, ram_limit):
    duration = duration or cfg.get("duration", 180)
    print(f"\n=== Scenario {name} "
          f"(sim={cfg['sim']}, load={cfg['load']}, {duration}s) ===")

    # fresh stop flag per scenario (watchdog shares it via test_common)
    stop_event.clear()
    test_common.abort_reason = None

    sim_proc = spawn_sim(cfg["sim"]) if cfg["sim"] else None
    time.sleep(10 if cfg["sim"] else 1)   # let the sim announce its nodes

    metrics = test_common.MetricsThread(
        os.path.join(out_dir, f"metrics_{name}.csv"), ram_limit_mb=ram_limit)
    metrics.start()

    load_summary = probe_summary = None
    try:
        if cfg["load"]:
            load_summary = api_load.run_load(
                os.path.join(out_dir, f"api_load_{name}.csv"),
                duration_s=duration, rest_users=10, sse_users=5)
        else:
            t0 = time.monotonic()
            while not stop_event.is_set() and time.monotonic() - t0 < duration:
                time.sleep(1.0)

        probe_summary = latency_probe.run_probe(
            os.path.join(out_dir, f"latency_{name}.csv"), count=10)
    finally:
        request_stop("scenario ended")
        if sim_proc:
            sim_proc.terminate()
            try:
                sim_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                sim_proc.kill()

    return {"load": load_summary, "latency": probe_summary,
            "abort_reason": test_common.abort_reason 
            if test_common.abort_reason not in (None, "scenario ended", "api_load duration elapsed")
            else None
            }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=list(SCENARIOS) + ["all"], default="all")
    ap.add_argument("--duration", type=int, default=180)
    ap.add_argument("--ram-limit", type=int, default=512)
    a = ap.parse_args()

    if not preflight():
        return

    run_dir = os.path.join(HERE, "results",
        "run_" + time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(run_dir, exist_ok=True)
    json.dump(test_common.device_info(),
              open(os.path.join(run_dir, "system_info.json"), "w"), indent=2)

    # Ctrl+C during a scenario = graceful end; report still builds
    signal.signal(signal.SIGINT, lambda s, f: request_stop("Ctrl+C"))
    names = list(SCENARIOS) if a.scenario == "all" else [a.scenario]

    results = {}
    for name in names:
        if test_common.abort_reason and test_common.abort_reason != "scenario ended":
            print(f"[run] stopping early: {test_common.abort_reason}")
            break
        results[name] = run_scenario(name, SCENARIOS[name],
                                      run_dir, None, a.ram_limit)

    summary = {"scenarios": results,
               "abort_reason": test_common.abort_reason
               if test_common.abort_reason not in (None, "scenario ended") else None}
    json.dump(summary, open(os.path.join(run_dir, "summary.json"), "w"), indent=2)

    report = build_report(run_dir)
    print(f"\n[run] DONE - open {report}")


if __name__ == "__main__":
    main()