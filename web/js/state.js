// The data the whole page shares.
// SSE handlers mutate these objects; render functions read them.
// Same role as parser/state.py.

let villages = {};      // villageId  -> village document
let nodes = {};        // "village/nodeId" -> node document
let alerts = [];       // newest first
let selectedKey = null; // "village/nodeId" of the node panel
let streamUp = false;

// ---- the one API helper everything uses ----

async function api(path) {
    const res = await fetch(API_BASE + path);
    if (!res.ok) throw new Error(`${path} -> ${res.status}`);
    return res.json();
}

// ---- key helpers ----

const nodeKey = (v, n) => `${v}/${n}`;

const fmtTime = (iso) => new Date(iso).toLocaleTimeString();

// ---- client-side diagnostics (what THIS browser experiences) ----
// The only measurement that can only be made from here.
const diag = { events: 0, eventRate: 0, lastEvent: null, restMs: null };