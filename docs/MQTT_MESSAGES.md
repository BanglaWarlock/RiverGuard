# RiverGuard — System Contract

The interface between the hardware mesh (ESP32 nodes, from the LoRa team)
and the cloud side. The parser is the adapter boundary: whatever the
firmware sends is translated into these writes, and nothing downstream
knows MQTT exists.

## MQTT messages (the input)

Topic structure: `mesh/{node_id}/{message_type}` — node identity comes
from the **topic**, never the payload. Timestamps are stamped by the
parser on arrival (UTC, naive — readers must interpret as UTC). All
subscriptions QoS 1 (delivery QoS = min of publisher's and subscriber's).

### Telemetry — `mesh/{node_id}/telemetry` (QoS 1)

```json
{
    "node":"0123ABCD",
    "uptime_minute":17,
    "sequence":4,
    "tx_packets":128,
    "rx_packets":96,
    "tx_bytes":5120,
    "rx_bytes":4200,
    "sf":7
}
```

| Field | Meaning |
|---|---|
| `node` | sender's id (hex, from firmware) |
| `uptime_minute` | minutes since boot — reboot detection (counter resets) |
| `sequence` | this node's telemetry counter — ordering/dedup key |
| `tx/rx_packets`, `tx/rx_bytes` | **cumulative** counters — rates/loss are *deltas* between consecutive reports, computed at read time |
| `sf` | current LoRa spreading factor |

One message per node per interval (≤5 min per the contract). Stored
**verbatim** (field semantics may evolve with firmware).

### Route report — `mesh/route/{node_id}` (QoS 0)

```json
{
    "s":23,
    "g":120000,
    "r":[{...one route per destination...}]
}
```

| Field | Meaning |
|---|---|
| `s` | sender's topology sequence counter (separate from telemetry's) |
| `g` | sender's uptime in ms at send time |
| `r` | the node's full routing table (Dijkstra output) |

Each route entry: `d` destination, `n` next hop, `h` hops, `c` total
cost, `l` first-hop cost, `ri`/`sn` first-hop RSSI/SNR (**may be null**),
`p` full path string (`A>B>C`), `a` ms since destination last heard,
`q` destination's topology sequence. Stored **verbatim**.

### Link blacklist — `mesh/control/blacklist` (QoS 0, **retained**)

Station → nodes link policy. Retained: the broker re-delivers the latest
version to every new subscriber (a restarted parser receives it
immediately; the parser dedups on `v`+`sequence`).

```json
{
    "v":2,
    "sequence":7,
    "edges":[["0123ABCD","AABBCCDD"]],
}
```

| Field | Meaning |
|---|---|
| `v` | **format version** — payload shape; changes when fields change |
| `sequence` | **edit counter** — monotonic per station; the ordering key |
| `edges` | node pairs whose direct link is disabled |

The v/sequence distinction: `sequence` says which policy is newer;
`v` says which payload *shape* a given policy uses.

## Database schema (the storage)

Five collections, one strategy each — chosen by how settled the data's
semantics are:

| Collection | Role | Strategy |
|---|---|---|
| `mesh_nodes` | **current state** — one doc per node | flattened latest values (denormalized on purpose) |
| `telemetry` | history | **raw** — verbatim payloads, one row per message |
| `route_reports` | history | **raw** — verbatim, one row per report |
| `blacklists` | history | **flattened** — format is final and versioned |
| `current_blacklist` | **current state** — single doc (`_id: "active"`) | flattened, overwritten per policy |

`mesh_nodes` doc (latest snapshot; history lives in the history
collections):

```json
{
    "node_id":"0123ABCD", 
    "first_seen":..., 
    "last_seen":...,
    "telemetry_seq":4, 
    "uptime_minute":17, 
    "sf":7,
    "tx_packets":128, 
    "rx_packets":96, 
    "tx_bytes":5120, 
    "rx_bytes":4200,
    "topology_seq":23, 
    "link_count":4, 
    "first_hop_rssi":-68, 
    "first_hop_snr":9.8
}
```

`last_seen` = any message type (telemetry or route both refresh it).
Derived values (packet loss, SF trends) are **computed at read time**
from history — never stored, so they can't disagree with the raw data.

Storage strategy per collection (the rule): **raw when the format may
evolve (telemetry, routes — field meanings confirmed late, versioned
blacklists suggest more changes); flattened when it's final and
queried (blacklists, current state).** Retention: pending decision
(90-day TTL designed, not yet active).

Indexes (each answers a named query):

| Index | Query it serves |
|---|---|
| `mesh_nodes.node_id` (unique) | node identity |
| `mesh_nodes.last_seen` | liveness ("seen since T") |
| `telemetry.(node_id, timestamp)` | per-node history |
| `route_reports.(node_id, timestamp)` | per-node reports |
| `blacklists.(v, sequence)` | version lookup + dedup |
| `*.timestamp` | time-window scans, reporter queries |

## Redis events (the notification)

One channel, `riverguard:mesh`. The parser publishes per message; the
API subscribes and forwards as SSE. **Pub/sub stores nothing** — the
database is truth, Redis is the tap on the shoulder.

Envelope shapes differ **per event type** — consumers dispatch on
`data.event` and handle each type explicitly (consumer does the
diligence):

```json
{
    "node_id":"0123ABCD", 
    "data":
        {
            "event":"telemetry", 
            "payload":{...}
        }, 
    "ts":"..."
}

{
    "node_id":"0123ABCD",
    "data":
        {
            "event":"route", 
            "s":23
        }, 
    "ts":"..."
}

{
    "data":
        {
            "event":"blacklist", 
            "payload":{...}
        }, 
    "ts":"..."
}
```

Telemetry and blacklist carry full payloads (small, always needed);
route carries a summary (large, frequent — consumers refetch via the
API when interested).

## REST API (the read side)

Read-only; the only door into the database. Base: `http://host:8000`.
Interactive docs at `/docs`; live stream at `/stream` (SSE).

| Endpoint | Returns |
|---|---|
| `GET /health` | service + dependencies status |
| `GET /stats` | computed summary: node counts, avg/worst RSSI, max SF, blocked edges |
| `GET /mesh/nodes` | all nodes, latest snapshots |
| `GET /mesh/nodes/{id}` | one node |
| `GET /mesh/nodes/{id}/telemetry?limit=` | per-node history, newest first |
| `GET /mesh/routes?node_id=&since=&limit=` | route reports |
| `GET /mesh/blacklists/current` | the active policy |
| `GET /mesh/blacklists?limit=` | policy history (sequence-ordered) |
| `GET /mesh/blacklists/{sequence}` | one policy version |

## Modes of running

| Mode | How | Config |
|---|---|---|
| Local dev | `python main.py` per service | `.env` (localhost) |
| Standalone container | `run_*_docker.bat` (debug; stack must be up) | `.env.docker` via `--env-file` |
| Full stack | `docker compose up -d` | `.env.docker` via compose injection |
| Tools/seeding | bats in `tools/`, `mongo/`, `redis/` | direct host ports |

Network naming: every service answers to `riverguard-<name>` on the
shared network (`riverguard-docker-network`), in all modes. Host
addresses (localhost:port) serve python-dev and external tools.
