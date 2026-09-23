# RiverGuard — MQTT Message Contract (v3)

The cloud-side contract between the hardware/master nodes, the parser, and everything downstream. The parser is the adapter boundary: whatever the firmware sends gets translated into these writes.

**Topic structure: `riverguard/{village}/{message_type}[/{node_id}[/status]]`**

Identity (village, node) comes from the **topic**, never the payload. Timestamps are stamped by the parser on arrival (UTC). All subscriptions QoS 1.

## Telemetry (per-parameter — one topic per measured value)

| Topic | Payload | Example | Sets on node doc |
|---|---|---|---|
| `riverguard/{v}/battery/{id}` | bare number or `{"value": V}` | `13.2` | `bat` |
| `riverguard/{v}/water/{id}` | float bitmask or `{"float_bits": B}` | `7` | `float_bits`, derived `water_level` |
| `riverguard/{v}/gps/{id}` | `{"lat", "lng", "gps_fix"?}` | `{"lat": 1.5540, "lng": 110.36, "gps_fix": true}` | `coordinates`, `gps_fix` |
| `riverguard/{v}/signal/{id}` | `{"rssi", "snr"}` | `{"rssi": -75, "snr": 7.5}` | `rssi`, `snr` (link to parent) |

Water bitmask: `0` = dry, `0b001` = 1 ft, `0b011` = 2 ft, `0b111` = 3 ft. Level = highest triggered sensor. Any telemetry is proof of life (node marked online).

## Alerts

| Topic | Payload | Example |
|---|---|---|
| `riverguard/{v}/alert/{id}` | `{"type", "value"?}` | `{"type": "flood", "value": 3}` |

Types: `flood` (value = level in ft), `battery` (voltage), `gps_moved` (meters), `gps_lost`, `gps_restored`.

## Lifecycle

| Topic | Payload | Example |
|---|---|---|
| `riverguard/{v}/announce/{id}` | `{"parent", "lat", "lng", "rssi"?, "snr"?}` | `{"parent": "SUTS-M01", "lat": 1.554, "lng": 110.36, "rssi": -70, "snr": 8.0}` |
| `riverguard/{v}/nodes/{id}/status` | `{"online": bool}` | `{"online": false}` |
| `riverguard/{v}/master/status` | `{"online": bool, "node_id"?}` | `{"online": true, "node_id": "SUTS-M01"}` |
| `riverguard/{v}/topology` | the tree itself | `{"SUTS-M01": {"SUTS-001": {"SUTS-002": {}}}}` |

- **Announce** = registration or re-meshing (parent, install GPS). Depth is computed by the parser by walking parent links — never taken from the payload. 

- The village is online if its master is online. Master id defaults to `{village}-M01` if not given.

- **Topology** is the master's authoritative tree: reconciles every node's parent, heals nodes whose announce was lost.

- **Auto-registration**: unknown nodes/villages referenced by any message are created on the spot; fields the message didn't carry stay `null` until learned. `parent_id: null` means "announce not received yet", never "no parent".

## Redis channels (parser → API, for SSE)

`riverguard:battery` · `riverguard:water` · `riverguard:gps` · `riverguard:signal` · `riverguard:alert` · `riverguard:node_status` · `riverguard:village_status` · `riverguard:topology`

Envelope (identical shape on every channel):

```json
{"village": "SUTS", "node_id": "SUTS-001", "data": {}, "ts": "2026-09-23T12:00:00"}
```

Pub/sub stores nothing — consumers must be subscribed before a publish to see anything. The API's `/stream` forwards these as SSE events with a channel field added.