// ============================================================
// Shared state - the one place data meets across files.
//
// NOTE: 'var' is DELIBERATE on every shared variable. In classic
// (non-module) scripts, top-level 'let'/'const' are private to their
// file - other script files cannot see them. 'var' and function
// declarations are shared globally. The next developer must not
// "modernize" these to let/const.
// ============================================================

// mesh data (latest snapshots from the API)
var meshNodes = {};        // node_id -> mesh node doc
var routesByNode = {};     // node_id -> newest raw route report payload
var activeBlacklist = null;// newest blacklist payload (policy)

// local node configuration (localStorage-backed; hardware never
// reports flood levels or positions - local IS the source)
var floodLevels = {};      // node_id -> { value: 0..1 }
var nodePositions = {};    // node_id -> { lat, lng }

// UI state
var selectedNode = null;   // node_id of the side card's subject
var selectedSideTab = "network";   // which side card tab is showing
var streamUp = false;     // SSE connected?
var placementPending = null; // node_id awaiting a map click, or null

// --- persistence helpers ---
function loadLocal() {
    try { floodLevels = JSON.parse(localStorage.getItem("rg_flood") || "{}"); }
    catch (e) { floodLevels = {}; }
    try { nodePositions = JSON.parse(localStorage.getItem("rg_positions") || "{}"); }
    catch (e) { nodePositions = {}; }
}
function saveFlood() { localStorage.setItem("rg_flood", JSON.stringify(floodLevels)); }
function savePositions() { localStorage.setItem("rg_positions", JSON.stringify(nodePositions)); }

// --- timestamps: the parser stores NAIVE UTC (no timezone suffix).
// JS parses bare ISO strings as LOCAL time - in UTC+8 that shifts
// everything by 8h. parseTs is the ONLY correct way to read any
// timestamp from the API. Never use new Date(ts) directly.
function parseTs(s) {
    if (s == null) return null;
    return new Date(String(s).endsWith("Z") ? s : s + "Z");
}

// --- island grouping: nodes grouped by which route-report island
// they belong to (everything reachable from a node shares its
// island; route paths give reachability for free).
function islands() {
    var groups = [];   // [{name: representative node, members: [...]}]
    var seen = {};
    Object.keys(meshNodes).forEach(function (id) {
        if (seen[id]) return;
        var members = {};
        members[id] = true;
        // every destination in this node's route table shares its island
        (routesByNode[id]?.r || []).forEach(function (rt) {
            if (meshNodes[rt.d]) members[rt.d] = true;
        });
        var list = Object.keys(members).sort();
        list.forEach(function (m) { seen[m] = true; });
        groups.push({ name: list[0], members: list });
    });
    return groups;
}