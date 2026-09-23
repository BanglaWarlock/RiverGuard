"""
RiverGuard simulator - fakes the hardware so the whole system has data
to show without any ESP32s.

It is a PURE MQTT PUBLISHER: it connects to the same broker as the real
master nodes and publishes exactly the topics the parser subscribes to
(see docs/MQTT_MESSAGES.md). It never touches MongoDB or Redis. To the
rest of the system it is indistinguishable from real hardware - which is
the point: parser, API, SSE stream and the future website are exercised
through the REAL pipeline, start to finish.

What it simulates:
  battery  - solar charging by day, drain by night, low-battery alerts
  water    - village weather (rain) raises float levels, dry spells
             recede them; reaching 3ft triggers flood alerts
  gps      - fixed position, occasional fix loss/restore
  signal   - rssi/snr to parent with jitter
  chaos    - nodes randomly drop out, revive later (sometimes re-meshed
             to a new parent - mesh healing)
  masters  - rarely blip offline; while a master is offline its nodes
             cannot publish at all (no bridge to the internet), then
             everything resyncs when it returns

How to run (3 terminals):
  1. python parser/parser.py
  2. python api/api.py            (optional - REST + /stream)
  3. python simulator/simulator.py

Ctrl+C stops it gracefully - it publishes everyone offline first.

Every message it sends is printed as the exact wire line
("  -> topic payload"), so the terminal doubles as a demo narration.

All tuning lives in the CONFIG section below. Uncomment random.seed()
for a repeatable demo.
"""

import signal
import threading
import time
import json
import random
import datetime

import paho.mqtt.client as mqtt

# random.seed(42)   # uncomment for a repeatable demo run

# ---------------------------------------------------------------------------
# CONFIG - the whole scenario lives here, nothing below needs to change
# ---------------------------------------------------------------------------

MQTT_BROKER = "broker.emqx.io"
MQTT_PORT = 1883

TICK_SECONDS = 1                  # one loop pass = one "tick"
ANNOUNCE_GAP_SECONDS = 2          # pacing between node announces at startup

WATER_EVERY_TICKS = 1             # 1s   between water checks per node
BATTERY_EVERY_TICKS = 5          # 5s  between battery updates
SIGNAL_EVERY_TICKS = 7            # 7s  between signal updates
GPS_EVERY_TICKS = 15              # 15s  between gps checks
TOPOLOGY_EVERY_TICKS = 45         # 45s  between master tree broadcasts

RAIN_MIN_TICKS, RAIN_MAX_TICKS = 8, 20    # how long a rain spell lasts
RISE_CHANCE = 0.9                 # water check during rain: level +1
RECEDE_CHANCE = 0.5               # water check while dry:    level -1
FLOOD_ALERT_COOLDOWN_TICKS = 60   # no repeat flood alert within 2 minutes

BATTERY_DAY_CHARGE = 0.08         # volts per update, daytime (solar)
BATTERY_NIGHT_DRAIN = 0.05        # volts per update, night
BATTERY_MIN, BATTERY_MAX = 11.0, 13.5
BATTERY_LOW_ALERT = 11.8          # alert once per dip below this

SIGNAL_JITTER_DB = 6              # rssi varies up to this below its base
SNR_MIN, SNR_MAX = 4.0, 10.0
GPS_FLIP_CHANCE = 0.15            # per gps check: fix flips

NODE_DEATH_CHANCE = 0.003         # per tick per online node (~1 dropout/min)
NODE_REVIVE_MIN_TICKS, NODE_REVIVE_MAX_TICKS = 15, 45
REMESH_CHANCE = 0.25              # revived node may attach to a new parent

MASTER_FLAP_CHANCE = 0.002        # per tick per village (rare)
MASTER_OUTAGE_MIN_TICKS, MASTER_OUTAGE_MAX_TICKS = 3, 8

# Villages are ~130km apart (Kuching vs Sri Aman) so the map shows two
# clearly separate clusters. Node coordinates cluster near their village.
VILLAGES = [
    {
        # Kuching area - the "calm" village
        "village": "SUTS",
        "master": "SUTS-M01",
        "rain_chance": 0.05,       # per tick while dry: a rain spell starts
        "nodes": [
            {"id": "SUTS-001", "parent": "SUTS-M01", "lat": 1.5545, "lng": 110.3608, "base_rssi": -70},
            {"id": "SUTS-002", "parent": "SUTS-M01", "lat": 1.5532, "lng": 110.3615, "base_rssi": -74},
            {"id": "SUTS-003", "parent": "SUTS-001", "lat": 1.5551, "lng": 110.3618, "base_rssi": -82},
            {"id": "SUTS-004", "parent": "SUTS-001", "lat": 1.5548, "lng": 110.3625, "base_rssi": -81},
            {"id": "SUTS-005", "parent": "SUTS-003", "lat": 1.5558, "lng": 110.3622, "base_rssi": -90},
            {"id": "SUTS-006", "parent": "SUTS-002", "lat": 1.5525, "lng": 110.3623, "base_rssi": -84,
             "bat_start": 11.6},   # weak battery: demo the low-battery alert
        ],
    },
    {
        # Sri Aman area - the "flood-prone" village
        "village": "SRAMAN",
        "master": "SRAMAN-M01",
        "rain_chance": 0.12,
        "nodes": [
            {"id": "SRAMAN-001", "parent": "SRAMAN-M01", "lat": 1.2338, "lng": 111.4534, "base_rssi": -71},
            {"id": "SRAMAN-002", "parent": "SRAMAN-001", "lat": 1.2343, "lng": 111.4541, "base_rssi": -83},
            {"id": "SRAMAN-003", "parent": "SRAMAN-001", "lat": 1.2339, "lng": 111.4549, "base_rssi": -85},
            {"id": "SRAMAN-004", "parent": "SRAMAN-M01", "lat": 1.2326, "lng": 111.4539, "base_rssi": -73},
            {"id": "SRAMAN-005", "parent": "SRAMAN-004", "lat": 1.2320, "lng": 111.4546, "base_rssi": -88},
        ],
    },
]

# ---------------------------------------------------------------------------
# Runtime state + plumbing
# ---------------------------------------------------------------------------

stop_event = threading.Event()
mqtt_client = None
publish_count = 0


def signal_handler(signum, frame):
    """Ctrl+C / docker stop - same pattern as the parser and API."""
    stop_event.set()


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def build_runtime_state():
    """Turn the CONFIG lists into working state (config + live values)."""
    villages = []
    for cfg in VILLAGES:
        nodes = []
        for n in cfg["nodes"]:
            nodes.append({
                # fixed facts (from config)
                "id": n["id"],
                "parent": n["parent"],
                "lat": n["lat"],
                "lng": n["lng"],
                "base_rssi": n["base_rssi"],
                # live values (start values, change as the sim runs)
                "bat": n.get("bat_start", 13.0),
                "level": 0,
                "rssi": n["base_rssi"],
                "snr": 8.0,
                "gps_fix": True,
                "online": True,
                "offline_for": 0,       # ticks left before a dead node revives
                "flood_cool": 0,        # ticks before flood alert may repeat
                "battery_low_alerted": False,
                # countdown timers, randomised so nodes don't fire in unison
                "water_in": random.randint(1, WATER_EVERY_TICKS),
                "battery_in": random.randint(1, BATTERY_EVERY_TICKS),
                "signal_in": random.randint(1, SIGNAL_EVERY_TICKS),
                "gps_in": random.randint(1, GPS_EVERY_TICKS),
            })
        villages.append({
            "village": cfg["village"],
            "master": cfg["master"],
            "rain_chance": cfg["rain_chance"],
            "nodes": nodes,
            "raining": False,
            "rain_left": 0,
            "master_online": True,
            "master_outage_for": 0,
            "topology_in": random.randint(1, TOPOLOGY_EVERY_TICKS),
        })
    return villages


def on_connect(client, userdata, flags, rc, props=None):
    if rc == 0:
        print(f"[MQTT] Connected to {MQTT_BROKER}")
    else:
        print(f"[MQTT] Connection failed with result code {rc}")


def on_disconnect(client, userdata, rc, props=None):
    if rc != 0:
        print(f"[MQTT] Unexpected disconnect (rc={rc}) - paho will retry")


def send(village, suffix, payload):
    """Publish one MQTT message and print exactly what went on the wire."""
    global publish_count
    topic = f"riverguard/{village}/{suffix}"
    mqtt_client.publish(topic, json.dumps(payload), qos=1)
    publish_count += 1
    print(f"  -> {topic} {json.dumps(payload)}")


# ---------------------------------------------------------------------------
# Simulated behaviors - one small function each
# ---------------------------------------------------------------------------

def is_daytime():
    """Solar charging window - decided by this machine's local clock."""
    return 6 <= datetime.datetime.now().hour < 18


def step_weather(village):
    """Rain spells: start by chance, run a random duration, then dry again."""
    if village["raining"]:
        village["rain_left"] -= 1
        if village["rain_left"] <= 0:
            village["raining"] = False
            print(f"[sim] {village['village']}: rain stopped")
    elif random.random() < village["rain_chance"]:
        village["raining"] = True
        village["rain_left"] = random.randint(RAIN_MIN_TICKS, RAIN_MAX_TICKS)
        print(f"[sim] {village['village']}: rain started ({village['rain_left']} ticks)")


def step_water(village, node):
    """Water level follows the weather. Published ONLY on change."""
    old = node["level"]
    if village["raining"] and random.random() < RISE_CHANCE:
        node["level"] = min(3, node["level"] + 1)
    elif not village["raining"] and random.random() < RECEDE_CHANCE:
        node["level"] = max(0, node["level"] - 1)

    if node["level"] != old:
        send(village["village"], f"water/{node['id']}",
             {"float_bits": (1 << node["level"]) - 1})
        print(f"[sim] {node['id']} water -> {node['level']}ft")

    # flood alert while at 3ft, at most once per cooldown window
    if node["level"] == 3 and node["flood_cool"] == 0:
        send(village["village"], f"alert/{node['id']}", {"type": "flood", "value": 3})
        print(f"[sim] {node['id']} FLOOD ALERT")
        node["flood_cool"] = FLOOD_ALERT_COOLDOWN_TICKS


def step_battery(village, node):
    """Solar battery: charge by day, drain by night, alert once per low dip."""
    if is_daytime():
        node["bat"] = min(BATTERY_MAX, node["bat"] + BATTERY_DAY_CHARGE)
    else:
        node["bat"] = max(BATTERY_MIN, node["bat"] - BATTERY_NIGHT_DRAIN)
    node["bat"] = round(node["bat"], 2)

    send(village["village"], f"battery/{node['id']}", {"value": node["bat"]})

    if node["bat"] < BATTERY_LOW_ALERT and not node["battery_low_alerted"]:
        send(village["village"], f"alert/{node['id']}",
             {"type": "battery", "value": node["bat"]})
        print(f"[sim] {node['id']} LOW BATTERY ALERT ({node['bat']}V)")
        node["battery_low_alerted"] = True
    if node["bat"] > BATTERY_LOW_ALERT + 0.2:
        node["battery_low_alerted"] = False


def step_signal(village, node):
    """Link to parent: rssi jitters below its base, snr floats."""
    node["rssi"] = node["base_rssi"] - random.randint(0, SIGNAL_JITTER_DB)
    node["snr"] = round(random.uniform(SNR_MIN, SNR_MAX), 1)
    send(village["village"], f"signal/{node['id']}",
         {"rssi": node["rssi"], "snr": node["snr"]})


def step_gps(village, node):
    """Position is fixed; the fix occasionally flips (lost/restored)."""
    if random.random() < GPS_FLIP_CHANCE:
        node["gps_fix"] = not node["gps_fix"]
        send(village["village"], f"gps/{node['id']}",
             {"lat": node["lat"], "lng": node["lng"], "gps_fix": node["gps_fix"]})
        alert_type = "gps_restored" if node["gps_fix"] else "gps_lost"
        send(village["village"], f"alert/{node['id']}", {"type": alert_type})
        print(f"[sim] {node['id']} gps_fix -> {node['gps_fix']}")


def step_chaos(village, node):
    """Rare random dropouts. While offline_for counts down, the node is dead."""
    if not node["online"]:
        node["offline_for"] -= 1
        if node["offline_for"] <= 0:
            revive_node(village, node)
        return

    if random.random() < NODE_DEATH_CHANCE:
        node["online"] = False
        node["offline_for"] = random.randint(NODE_REVIVE_MIN_TICKS, NODE_REVIVE_MAX_TICKS)
        send(village["village"], f"nodes/{node['id']}/status", {"online": False})
        print(f"[sim] {node['id']} went OFFLINE (revives in {node['offline_for']} ticks)")


def revive_node(village, node):
    """Dead node comes back: re-announces, sometimes to a new parent."""
    node["online"] = True
    if random.random() < REMESH_CHANCE:
        candidates = [village["master"]] + [n["id"] for n in village["nodes"]
                                            if n is not node and n["online"]]
        node["parent"] = random.choice(candidates)
        print(f"[sim] {node['id']} re-meshed, new parent {node['parent']}")
    announce_node(village, node)
    publish_full_state(village, node)
    print(f"[sim] {node['id']} back ONLINE")


def announce_node(village, node):
    """Deployment message: parent, install position, link quality."""
    send(village["village"], f"announce/{node['id']}", {
        "parent": node["parent"],
        "lat": node["lat"],
        "lng": node["lng"],
        "rssi": node["rssi"],
        "snr": node["snr"],
    })


def publish_full_state(village, node):
    """All four telemetry values at once - used at deploy and after outages."""
    v = village["village"]
    send(v, f"battery/{node['id']}", {"value": node["bat"]})
    send(v, f"water/{node['id']}", {"float_bits": (1 << node["level"]) - 1})
    send(v, f"gps/{node['id']}",
         {"lat": node["lat"], "lng": node["lng"], "gps_fix": node["gps_fix"]})
    send(v, f"signal/{node['id']}", {"rssi": node["rssi"], "snr": node["snr"]})


def step_master(village):
    """
    Masters rarely blip offline. While a master is down its nodes cannot
    publish at all - there is no bridge to the internet, exactly like the
    real mesh. When it returns, everyone resyncs their current values.
    """
    v = village["village"]
    if village["master_online"]:
        if random.random() < MASTER_FLAP_CHANCE:
            village["master_online"] = False
            village["master_outage_for"] = random.randint(
                MASTER_OUTAGE_MIN_TICKS, MASTER_OUTAGE_MAX_TICKS)
            send(v, "master/status", {"online": False, "node_id": village["master"]})
            print(f"[sim] {v} master OFFLINE ({village['master_outage_for']} ticks) - village silent")
        return

    village["master_outage_for"] -= 1
    if village["master_outage_for"] <= 0:
        village["master_online"] = True
        send(v, "master/status", {"online": True, "node_id": village["master"]})
        print(f"[sim] {v} master back ONLINE - nodes resync")
        for node in village["nodes"]:
            if node["online"]:
                publish_full_state(village, node)


def build_tree(village):
    """Mesh tree from current parent links: {master: {child: {grandchild: {}}}}"""
    children_of = {}
    for node in village["nodes"]:
        children_of.setdefault(node["parent"], []).append(node["id"])

    def attach(node_id):
        return {child: attach(child) for child in children_of.get(node_id, [])}

    return {village["master"]: attach(village["master"])}


def step_topology(village):
    """Periodic authoritative tree broadcast, like the real master would."""
    village["topology_in"] -= 1
    if village["topology_in"] <= 0:
        village["topology_in"] = TOPOLOGY_EVERY_TICKS
        send(village["village"], "topology", build_tree(village))


# ---------------------------------------------------------------------------
# Startup, main loop, shutdown
# ---------------------------------------------------------------------------

def startup(villages):
    """Boot the network: masters online, then nodes announce one by one."""
    for village in villages:
        v = village["village"]
        send(v, "master/status", {"online": True, "node_id": village["master"]})
        print(f"[sim] {v}: master {village['master']} ONLINE")
        for node in village["nodes"]:
            if stop_event.is_set():
                return
            announce_node(village, node)
            print(f"[sim] {v}: deployed {node['id']} (parent {node['parent']})")
            publish_full_state(village, node)
            stop_event.wait(ANNOUNCE_GAP_SECONDS)   # interruptible sleep
        stop_event.wait(ANNOUNCE_GAP_SECONDS)


def run_loop(villages):
    """
    One tick at a time: master health, weather, then each online node's
    countdown timers fire their behaviors. While a master is offline the
    whole village is skipped (simplification: state freezes instead of
    quietly advancing - the visible effect, a data gap then a resync
    burst, is the same as reality).
    """
    tick = 0
    while not stop_event.is_set():
        tick += 1
        for village in villages:
            step_master(village)
            if not village["master_online"]:
                continue

            step_weather(village)

            for node in village["nodes"]:
                step_chaos(village, node)
                if not node["online"]:
                    continue

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

                node["gps_in"] -= 1
                if node["gps_in"] <= 0:
                    node["gps_in"] = GPS_EVERY_TICKS
                    step_gps(village, node)

                if node["flood_cool"] > 0:
                    node["flood_cool"] -= 1

            step_topology(village)

        stop_event.wait(TICK_SECONDS)


def shutdown(villages):
    """Graceful: every online node offline, then every master offline."""
    print("\n[sim] shutting down - marking everyone offline")
    for village in villages:
        v = village["village"]
        for node in village["nodes"]:
            if node["online"]:
                send(v, f"nodes/{node['id']}/status", {"online": False})
        send(v, "master/status", {"online": False, "node_id": village["master"]})


def main():
    global mqtt_client

    villages = build_runtime_state()
    node_count = sum(len(v["nodes"]) for v in villages)
    print(f"[sim] RiverGuard simulator - {node_count} nodes in {len(villages)} villages")

    # Same MQTT client style as the parser, deliberately
    mqtt_client = mqtt.Client()
    mqtt_client.on_connect = on_connect
    mqtt_client.on_disconnect = on_disconnect
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    mqtt_client.loop_start()
    stop_event.wait(1.0)   # let the connection establish before publishing

    startup(villages)
    print("[sim] steady state - watch the parser / API / stream terminals")
    run_loop(villages)

    shutdown(villages)
    mqtt_client.loop_stop()
    mqtt_client.disconnect()
    print(f"[sim] done - {publish_count} messages published")


if __name__ == "__main__":
    main()