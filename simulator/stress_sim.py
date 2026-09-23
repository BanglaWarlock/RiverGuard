"""
RiverGuard stress simulator - load generator for testing.

Publishes the SAME MQTT contract as simulator.py, but built to scale:
  - many nodes per village, generated branching trees
  - a RAMP: new nodes deployed over time up to a cap (exercises
    auto-registration and topology growth under load)
  - fast message cadence, controlled by tick-based knobs
  - NO per-message printing - counters only, one summary line every
    STATS_EVERY_SECONDS (printing is itself a bottleneck at load)

The broker comes from MQTT_BROKER env var (default: the public one), so
the stress harness can point it anywhere.

Spawned and killed by tools/stress/run_stress.py - it is test equipment,
not part of the system under test. Data it produces is throwaway;
run the db clear script afterwards.

Usage:  python stress_sim.py    (Ctrl+C stops; does NOT mark nodes
        offline on exit - stress data is throwaway)
"""

import signal
import threading
import time
import json
import random
import datetime
import os

import paho.mqtt.client as mqtt

# ---------------------------------------------------------------------------
# CONFIG - all load knobs live here
# ---------------------------------------------------------------------------

MQTT_BROKER = os.getenv("MQTT_BROKER", "broker.emqx.io")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

NODES_START = 20              # nodes per village at boot
NODES_MAX = 50                # cap per village (total = x villages)
RAMP_ADD = 5                  # nodes added per village...
RAMP_EVERY_TICKS = 25         # ...every this many ticks
CHILDREN_MIN, CHILDREN_MAX = 2, 4   # branching shape of the tree

# new, set different aprameters
#  paced mode (default) knobs 
TICK_SECONDS = 0.2
SIGNAL_EVERY_TICKS = 2        # 0.4s per node - the main chatter driver
WATER_EVERY_TICKS = 10
BATTERY_EVERY_TICKS = 50
TOPOLOGY_EVERY_TICKS = 150

# escalation mode (ESCALATE=1) 
# The generator climbs one LEVEL every ESCALATE_EVERY_SECONDS until it
# saturates, holding the last rate thereafter. Each level sets the whole
# config at once: (signal_every_ticks, nodes_per_village, tick_seconds).
# The published rate is still approximate - the real number is the
# [stats] rate line, compared against the parser's own [stats].
LEVELS = [
    (2,  20,  0.20),   # ~100 msg/s
    (1,  20,  0.20),   # ~200
    (1,  40,  0.20),   # ~400
    (1,  60,  0.10),   # ~1200
    (1,  80,  0.10),   # ~1600
    (1, 100, 0.10),   # ~2000
    (1, 100, 0.05),   # ~4000
    (1, 150, 0.05),   # ~6000
]
ESCALATE = os.getenv("ESCALATE", "0") == "1"
ESCALATE_EVERY_SECONDS = 60        # hold each level this long

#  unpaced mode (UNPACED=1) - "find the machine's ceiling" ---
# No pacing at all: every node publishes signal every single loop pass,
# the loop never sleeps, ramp/growth disabled (nodes at max from boot).
# The achieved rate becomes a MEASURED OUTPUT instead of a configured
# input. When the generator itself saturates, you learn ITS ceiling -
# which is a FLOOR on the parser's true limit. To go beyond one
# generator, run several with different VILLAGE_PREFIX values.
UNPACED = os.getenv("UNPACED", "0") == "1"
VILLAGE_PREFIX = os.getenv("VILLAGE_PREFIX", "")

# --- village names: prefixed so parallel generators don't collide ---
VILLAGE_DEFS = [              # name + map center (clusters stay apart)
    {"village": f"{VILLAGE_PREFIX}LOAD1", "lat": 1.554, "lng": 110.360},
    {"village": f"{VILLAGE_PREFIX}LOAD2", "lat": 1.233, "lng": 111.453},
]



RAIN_CHANCE = 0.30            # per weather step, per village
RAIN_MIN_TICKS, RAIN_MAX_TICKS = 5, 15
RISE_CHANCE, RECEDE_CHANCE = 0.6, 0.3

BATTERY_DAY_CHARGE, BATTERY_NIGHT_DRAIN = 0.08, 0.05
BATTERY_MIN, BATTERY_MAX = 11.0, 13.5

STATS_EVERY_SECONDS = 5

# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------

stop_event = threading.Event()
mqtt_client = None

counters = {"battery": 0, "water": 0, "gps": 0, "signal": 0,
            "announce": 0, "topology": 0, "status": 0}
total_published = 0


def signal_handler(signum, frame):
    stop_event.set()


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def on_connect(client, userdata, flags, rc, props=None):
    print(f"[MQTT] connected: {rc == 0}")


def send(village, suffix, payload):
    """Publish one message. Counts it. NEVER prints per message."""
    global total_published
    mqtt_client.publish(f"riverguard/{village}/{suffix}", json.dumps(payload), qos=1)
    total_published += 1


def is_daytime():
    return 6 <= datetime.datetime.now().hour < 18

# ---------------------------------------------------------------------------
# Node/village generation
# ---------------------------------------------------------------------------

def make_node(village_cfg, index, parent):
    """Synthetic node: coordinates spread wider as the village grows."""
    spread = 0.008 + (index ** 0.5) * 0.0012
    return {
        "id": f"{village_cfg['village']}-{index:03d}",
        "parent": parent,
        "lat": village_cfg["lat"] + random.uniform(-spread, spread),
        "lng": village_cfg["lng"] + random.uniform(-spread, spread),
        "online": True,
        "level": 0,
        "bat": 13.0,
        "rssi": -70 - random.randint(0, 20),
        "snr": 8.0,
        "water_in": random.randint(1, WATER_EVERY_TICKS),
        "battery_in": random.randint(1, BATTERY_EVERY_TICKS),
        "signal_in": random.randint(1, SIGNAL_EVERY_TICKS),
    }


def deploy_node(village_cfg, node):
    """Announce + all four telemetry values (like a real deployment)."""
    v = village_cfg["village"]
    send(v, f"announce/{node['id']}", {
        "parent": node["parent"], "lat": node["lat"], "lng": node["lng"],
        "rssi": node["rssi"], "snr": node["snr"]})
    counters["announce"] += 1
    send(v, f"battery/{node['id']}", {"value": node["bat"]})
    send(v, f"water/{node['id']}", {"float_bits": (1 << node["level"]) - 1})
    send(v, f"signal/{node['id']}", {"rssi": node["rssi"], "snr": node["snr"]})
    counters["battery"] += 1
    counters["water"] += 1
    counters["signal"] += 1


def build_village(village_cfg):
    """Boot tree: BFS from the master, each node gets 2-4 children."""
    nodes = []
    queue = [f"{village_cfg['village']}-M01"]
    while len(nodes) < NODES_START and queue:
        parent = queue.pop(0)
        for _ in range(random.randint(CHILDREN_MIN, CHILDREN_MAX)):
            if len(nodes) >= NODES_START:
                break
            node = make_node(village_cfg, len(nodes) + 1, parent)
            nodes.append(node)
            queue.append(node["id"])
    # safety: if the queue ran dry before NODES_START, top up flat
    while len(nodes) < NODES_START:
        nodes.append(make_node(
            village_cfg, len(nodes) + 1,
            queue[-1] if queue else f"{village_cfg['village']}-M01"))

    return {
        "cfg": village_cfg,
        "master": f"{village_cfg['village']}-M01",
        "nodes": nodes,
        "raining": False, "rain_left": 0,
        "ramp_in": RAMP_EVERY_TICKS,
        "topology_in": TOPOLOGY_EVERY_TICKS,
    }

# ---------------------------------------------------------------------------
# Per-tick behaviors
# ---------------------------------------------------------------------------

def step_ramp(village):
    """Deploy more nodes over time, attached to random existing ones."""
    village["ramp_in"] -= 1
    if village["ramp_in"] > 0 or len(village["nodes"]) >= NODES_MAX:
        return
    village["ramp_in"] = RAMP_EVERY_TICKS

    parents = [village["master"]] + [n["id"] for n in village["nodes"]]
    for _ in range(RAMP_ADD):
        if len(village["nodes"]) >= NODES_MAX:
            break
        node = make_node(village["cfg"], len(village["nodes"]) + 1,
                         random.choice(parents))
        village["nodes"].append(node)
        deploy_node(village["cfg"], node)
    print(f"[ramp] {village['cfg']['village']}: "
          f"{len(village['nodes'])} nodes deployed")


def step_weather(village):
    if village["raining"]:
        village["rain_left"] -= 1
        if village["rain_left"] <= 0:
            village["raining"] = False
    elif random.random() < RAIN_CHANCE:
        village["raining"] = True
        village["rain_left"] = random.randint(RAIN_MIN_TICKS, RAIN_MAX_TICKS)


def step_water(village, node):
    old = node["level"]
    if village["raining"] and random.random() < RISE_CHANCE:
        node["level"] = min(3, node["level"] + 1)
    elif not village["raining"] and random.random() < RECEDE_CHANCE:
        node["level"] = max(0, node["level"] - 1)
    if node["level"] != old:
        send(village["cfg"]["village"], f"water/{node['id']}",
             {"float_bits": (1 << node["level"]) - 1})
        counters["water"] += 1
        if node["level"] == 3:   # alert traffic too
            send(village["cfg"]["village"], f"alert/{node['id']}",
                 {"type": "flood", "value": 3})
            counters["status"] += 1


def step_battery(village, node):
    if is_daytime():
        node["bat"] = min(BATTERY_MAX, node["bat"] + BATTERY_DAY_CHARGE)
    else:
        node["bat"] = max(BATTERY_MIN, node["bat"] - BATTERY_NIGHT_DRAIN)
    node["bat"] = round(node["bat"], 2)
    send(village["cfg"]["village"], f"battery/{node['id']}",
         {"value": node["bat"]})
    counters["battery"] += 1


def step_signal(village, node):
    node["rssi"] = -70 - random.randint(0, 25)
    node["snr"] = round(random.uniform(4.0, 10.0), 1)
    send(village["cfg"]["village"], f"signal/{node['id']}",
         {"rssi": node["rssi"], "snr": node["snr"]})
    counters["signal"] += 1


def step_topology(village):
    village["topology_in"] -= 1
    if village["topology_in"] > 0:
        return
    village["topology_in"] = TOPOLOGY_EVERY_TICKS

    children_of = {}
    for n in village["nodes"]:
        children_of.setdefault(n["parent"], []).append(n["id"])

    def attach(node_id):
        return {c: attach(c) for c in children_of.get(node_id, [])}

    send(village["cfg"]["village"], "topology",
         {village["master"]: attach(village["master"])})
    counters["topology"] += 1
    
# ---------------------------------------------------------------------------
# Escalation controller (ESCALATE mode)
# ---------------------------------------------------------------------------

current_level = 0          # index into LEVELS
level_started = None       # when the current level began
saturation_strikes = 0     # consecutive stats windows with tick overrun


def apply_level(i):
    """Set the whole pacing config for level i, at once."""
    global SIGNAL_EVERY_TICKS, TICK_SECONDS, NODES_MAX, WATER_EVERY_TICKS, BATTERY_EVERY_TICKS
    signal_every, nodes_cap, tick_s = LEVELS[i]
    SIGNAL_EVERY_TICKS = signal_every
    TICK_SECONDS = tick_s
    NODES_MAX = nodes_cap
    WATER_EVERY_TICKS = 3
    BATTERY_EVERY_TICKS = 10
    # re-aim existing nodes' signal countdowns at the new, faster rate
    for village in villages:
        for node in village["nodes"]:
            node["signal_in"] = min(node["signal_in"], signal_every)


def step_escalation(now):
    """Called once per tick. Climb until saturated or at the top."""
    global current_level, level_started

    if not ESCALATE or current_level < 0:
        return   # mode off, or already saturated/holding

    if level_started is None:
        level_started = now
        apply_level(0)
        print(f"[escalate] level 1/{len(LEVELS)}: "
              f"~{len(villages) * LEVELS[0][1] * 5}/s target")
        return

    if now - level_started >= ESCALATE_EVERY_SECONDS:
        nxt = current_level + 1
        if nxt >= len(LEVELS):
            print("[escalate] max level reached - holding")
            current_level = -2          # hold at top
            return
        current_level = nxt
        apply_level(nxt)
        level_started = now
        print(f"[escalate] level {nxt + 1}/{len(LEVELS)}: signal every "
              f"{LEVELS[nxt][0]} ticks, cap {LEVELS[nxt][1]} nodes/village, "
              f"tick {LEVELS[nxt][2]}s")

# ---------------------------------------------------------------------------
# Stats (the ONLY printing this program does while running)
# ---------------------------------------------------------------------------

stats_last = {"t": None, "total": 0, "tick_time": 0.0, "ticks": 0}


def print_stats(tick_duration):
    stats_last["tick_time"] += tick_duration
    stats_last["ticks"] += 1
    now = time.monotonic()
    if stats_last["t"] is None:
        stats_last["t"] = now
        return
    if now - stats_last["t"] < STATS_EVERY_SECONDS:
        return

    dt = now - stats_last["t"]
    rate = (total_published - stats_last["total"]) / dt
    avg_tick = stats_last["tick_time"] / max(stats_last["ticks"], 1)
    nodes = sum(len(v["nodes"]) for v in villages)
    over = (avg_tick / TICK_SECONDS - 1) * 100

    print(f"[stats] t={now - start_time:6.0f}s  nodes={nodes:3d}  "
          f"total={total_published:7d}  rate={rate:6.1f}/s  "
          f"tick avg {avg_tick:.3f}s ({over:+.0f}% vs {TICK_SECONDS}s)  "
          f"{counters}")
    stats_last.update(t=now, total=total_published, tick_time=0.0, ticks=0)
    
    # generator saturation: the tick loop itself takes almost as long as
    # the tick period - this process physically cannot publish faster.
    # Only meaningful in ESCALATE mode (paced mode WANTS small ticks).
    global saturation_strikes
    if ESCALATE and avg_tick > TICK_SECONDS * 0.8:
        saturation_strikes += 1
        if saturation_strikes >= 2 and current_level >= 0:
            print(f"[escalate] GENERATOR SATURATED at level "
                  f"{current_level + 1} - holding this rate")
            current_level = -1
    else:
        saturation_strikes = 0

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

start_time = None


def main():
    global mqtt_client, start_time, villages
    start_time = time.monotonic()

    total_nodes = len(VILLAGE_DEFS) * NODES_START
    print(f"[stress] {len(VILLAGE_DEFS)} villages, {total_nodes} nodes at boot, "
          f"ramp to {len(VILLAGE_DEFS) * NODES_MAX}, broker {MQTT_BROKER}")

    mqtt_client = mqtt.Client()
    mqtt_client.on_connect = on_connect
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    mqtt_client.loop_start()
    stop_event.wait(1.0)

    villages = [build_village(cfg) for cfg in VILLAGE_DEFS]
    for village in villages:                     # boot burst (itself a spike)
        send(village["cfg"]["village"], "master/status",
             {"online": True, "node_id": village["master"]})
        for node in village["nodes"]:
            deploy_node(village["cfg"], node)
    print("[stress] boot burst done - steady state begins")

    while not stop_event.is_set():
        tick_start = time.monotonic()
        step_escalation(tick_start)
        for village in villages:
            if not UNPACED:
                step_ramp(village)
            step_weather(village)
            for node in village["nodes"]:
                node["water_in"] -= 1
                if node["water_in"] <= 0:
                    node["water_in"] = WATER_EVERY_TICKS
                    step_water(village, node)
                node["battery_in"] -= 1
                if node["battery_in"] <= 0:
                    node["battery_in"] = BATTERY_EVERY_TICKS
                    step_battery(village, node)
                node["signal_in"] -= 1
                if node["signal_in"] <= 0:
                    node["signal_in"] = SIGNAL_EVERY_TICKS
                    step_signal(village, node)
            step_topology(village)

        elapsed = time.monotonic() - tick_start
        print_stats(elapsed)
        if UNPACED:
            continue   # no pacing, just run as fast as possible
        stop_event.wait(max(0, TICK_SECONDS - elapsed))   # keep tick rate honest

    print(f"[stress] stopped - {total_published} messages published")
    mqtt_client.loop_stop()
    mqtt_client.disconnect()


if __name__ == "__main__":
    main()