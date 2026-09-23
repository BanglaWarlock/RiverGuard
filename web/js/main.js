// Boot sequence and page wiring - the only file that orchestrates.

async function loadAll() {
    const t0 = performance.now();
    // 1. villages (one call) and their nodes (one call each)
    const villageList = await api("/villages");
    const nodeLists = await Promise.all(
        villageList.map((v) => api(`/villages/${v.village_id || v._id}/nodes`)
            .catch(() => []))
    );

    villages = {};
    nodes = {};
    villageList.forEach((v) => { villages[v.village_id || v._id] = v; });
    nodeLists.flat().forEach((n) => { nodes[nodeKey(n.village_id, n.node_id)] = n; });

    // 2. recent alerts + global stats
    alerts = await api(`/alerts?limit=${MAX_ALERT_ROWS}`).catch(() => []);
    diag.restMs = Math.round(performance.now() - t0);
    await refreshStats();
}

// Re-fetch a single village and its nodes (used when SSE mentions a
// node this page has never seen - it must have been announced after load).
async function loadVillage(v) {
    const [villageDoc, nodeList] = await Promise.all([
        api(`/villages/${v}`), api(`/villages/${v}/nodes`),
    ]);
    villages[v] = villageDoc;
    nodeList.forEach((n) => { nodes[nodeKey(v, n.node_id)] = n; });
    renderVillageList();
    renderMarkers();
    renderLines();
}

async function refreshStats() {
    const s = await api("/stats").catch(() => ({}));
    renderStats(s);
}

function renderAll() {
    renderStats();
    renderVillageList();
    renderMarkers();
    renderLines();
    renderAlertFeed();
    if (selectedKey) renderNodePanel();
}

function renderStats(s) {
    const el = document.getElementById("stats");
    if (!s) { el.innerHTML = "…"; return; }

    const total = (s.river_nodes_online || 0) + (s.river_nodes_offline || 0);
    const evPerSec = (eventTimes.length / 10).toFixed(1);   // last 10s window

    el.innerHTML =
        `<span>${s.masters_online || 0} master${s.masters_online === 1 ? "" : "s"} online</span>` +
        `<span>${s.river_nodes_online || 0}/${total} nodes online</span>` +
        `<span>stream <span class="dot ${streamUp ? "live" : ""}"></span> ${evPerSec}/s</span>`;
}

async function boot() {
    // 1. The map (Kuching <-> Sri Aman area; will auto-fit to nodes)
    map = L.map("map").setView([1.4, 110.9], 8);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 18,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(map);

    // 2. Current state, then draw everything
    await loadAll().catch((e) => console.error("initial load failed", e));
    renderAll();

    // 3. Fit the view to all nodes once
    const coords = Object.values(nodes)
        .filter((n) => n.coordinates)
        .map((n) => [n.coordinates.lat, n.coordinates.lng]);
    if (coords.length) map.fitBounds(L.latLngBounds(coords), { padding: [40, 40] });

    // 4. Periodically refresh the stats strip (numbers + diagnostics)
    setInterval(refreshStats, 5000);

    // 5. Go live
    connectStream();
}

document.getElementById("refresh-btn").onclick = async () => {
    await loadAll().catch(() => { });
    renderAll();
};

boot();