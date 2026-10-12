// ============================================================
// Shared state - the one place data meets across files.
//
// NOTE: 'var' is DELIBERATE on every shared variable. In classic
// (non-module) scripts, top-level 'let'/'const' are private to
// their file - other script files cannot see them. 'var' and
// function declarations are shared globally. The next developer
// must not "modernize" these to let/const.
// ============================================================

// mesh data (latest snapshots from the API)
var meshNodes = {};        // node_id -> mesh node doc
var routesByNode = {};     // node_id -> newest raw route report payload
var activeBlacklist = null;// newest blacklist payload (policy)

// flood demo data (localStorage-backed)
var floodLevels = {};      // node_id -> { value: 0..1, source: "local" }

// UI state
var selectedNode = null;   // node_id of the side card's subject
var sideTab = "network";   // which side card tab is showing
var streamUp = false;     // SSE connected?

// --- flood levels persistence ---
function loadFlood() {
    try { floodLevels = JSON.parse(localStorage.getItem("rg_flood") || "{}"); }
    catch (e) { floodLevels = {}; }
}
function saveFlood() {
    localStorage.setItem("rg_flood", JSON.stringify(floodLevels));
}