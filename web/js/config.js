// RiverGuard website configuration.
// Changing where the API is, colors, labels, or thresholds.


// "" = same origin (the API serves this site). Hosted elsewhere
// (e.g. Vercel)? Set this to the public API URL.
const API_BASE = "http://127.0.0.1:8000";

// water levels 0..3 ft -> color
const LEVEL_COLORS = ["#2e7d32", "#f9a825", "#ef6c00", "#c62828"];
const LEVEL_LABELS = ["dry", "1 ft", "2 ft", "3 ft"];

// float_bits (0-7) -> water level in ft
const BITS_TO_LEVEL = [0, 1, 2, 2, 3, 3, 3, 3];

// alert types -> badge look
const ALERT_META = {
    flood: { icon: "🌊", label: "FLOOD", color: "#c62828" },
    battery: { icon: "🔋", label: "BATTERY", color: "#ef6c00" },
    gps_moved: { icon: "📍", label: "GPS MOVED", color: "#5e35b1" },
    gps_lost: { icon: "📡", label: "GPS LOST", color: "#5e35b1" },
    gps_restored: { icon: "📡", label: "GPS BACK", color: "#43a047" },
};

const MAX_ALERT_ROWS = 50;     // how many alerts the feed keeps
const BATTERY_LOW_V = 11.8;    // below this = red in the node panel
const RSSI_GOOD = -75, RSSI_OK = -85;   // link color thresholds (dBm)