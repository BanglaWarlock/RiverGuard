// map defaults: Kuching area until nodes are placed
const MAP_CENTER = [1.55, 110.35];
const MAP_ZOOM = 11;

// All knobs: API address, palettes, thresholds.
const API_BASE = "http://127.0.0.1:8000";

const LINK_GOOD = -75, LINK_MID = -85;   // RSSI thresholds (dBm)

// continuous flood value -> class (0..3) and label/color
const FLOOD_CLASSES = [
    { max: 0.25, label: "Dry", color: "var(--level0)" },
    { max: 0.60, label: "Watch", color: "var(--level1)" },
    { max: 0.85, label: "Warning", color: "var(--level2)" },
    { max: 1.01, label: "Flood", color: "var(--level3)" },
];
const floodClass = (v) =>
    FLOOD_CLASSES.find(c => v < c.max) || FLOOD_CLASSES[FLOOD_CLASSES.length - 1];

const linkColor = (rssi) =>
    rssi == null ? "var(--link-none)"
        : rssi > LINK_GOOD ? "var(--link-good)"
            : rssi > LINK_MID ? "var(--link-mid)"
                : "var(--link-bad)";