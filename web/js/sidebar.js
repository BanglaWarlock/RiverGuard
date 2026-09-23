// The sidebar: village cards, the selected-node detail panel,
// and its water-level sparkline.
// A developer changing what INFORMATION is shown edits only this.

function renderVillageList() {
    const el = document.getElementById("village-list");
    el.innerHTML = "";

    for (const id of Object.keys(villages).sort()) {
        const v = villages[id];
        const vNodes = Object.values(nodes).filter((n) => n.village_id === id);

        // worst water level in the village colors the card edge
        const maxLevel = vNodes.reduce((m, n) => Math.max(m, n.water_level || 0), 0);

        const card = document.createElement("div");
        card.className = "village-card" + (v.is_online ? "" : " offline");
        card.style.borderLeftColor = v.is_online ? LEVEL_COLORS[maxLevel] : "#b0bec5";
        card.innerHTML =
            `<div class="row1"><span>${id}</span>` +
            `<span class="chip ${v.is_online ? "online-chip" : "offline-chip"}">` +
            `${v.is_online ? "online" : "offline"}</span></div>` +
            `<div class="counts">master ${v.master_id || "?"} · ` +
            `${v.river_nodes_online || 0}/${v.total_river_nodes || vNodes.length} nodes up · ` +
            `water ≤ ${LEVEL_LABELS[maxLevel]}</div>`;

        card.onclick = () => flyToVillage(id);
        el.appendChild(card);
    }
}

// node detail panel

function selectNode(key) {
    selectedKey = key;
    renderNodePanel();
}

function renderNodePanel() {
    const node = nodes[selectedKey];
    const section = document.getElementById("node-section");
    if (!node) { section.hidden = true; return; }

    section.hidden = false;
    document.getElementById("node-title").textContent =
        `${node.node_id} · ${node.village_id}`;

    const online = node.status !== "offline";
    const level = node.water_level || 0;

    document.getElementById("node-details").innerHTML =
        `<dl>
      <dt>Status</dt><dd><span class="chip ${online ? "online-chip" : "offline-chip"}">${node.status || "?"}</span></dd>
      <dt>Water level</dt><dd><span class="chip" style="background:${LEVEL_COLORS[level]}">${LEVEL_LABELS[level]}</span>
        <small>float_bits ${node.float_bits ?? "?"}</small></dd>
      <dt>Battery</dt><dd style="color:${node.bat != null && node.bat < BATTERY_LOW_V ? "#c62828" : "inherit"}">${node.bat != null ? node.bat.toFixed(2) + " V" : "—"}</dd>
      <dt>Link to parent</dt><dd>${node.rssi != null ? node.rssi + " dBm" : "—"} · ${node.snr != null ? node.snr + " dB" : "—"}
        <small style="color:${linkColor(node.rssi)}">●</small></dd>
      <dt>Parent / depth</dt><dd>${node.parent_id || "unknown"} · ${node.depth != null ? node.depth + " hop(s)" : "?"}</dd>
      <dt>GPS</dt><dd>${node.gps_fix ? "fix" : "no fix"}
        ${node.coordinates ? `<small>${node.coordinates.lat.toFixed(4)}, ${node.coordinates.lng.toFixed(4)}</small>` : ""}</dd>
      <dt>Last seen</dt><dd>${node.last_seen ? fmtTime(node.last_seen) : "—"}</dd>
      <dt>Alerts</dt><dd>${formatAlertCounts(node.alert_counts)}</dd>
    </dl>
    <div class="spark"><div class="label">recent water level (history)</div>
      <div id="spark-slot">loading…</div></div>`;

    loadSparkline(node.village_id, node.node_id);
}

function formatAlertCounts(counts) {
    if (!counts || !Object.keys(counts).length) return "none";
    return Object.entries(counts)
        .map(([type, n]) => {
            const meta = ALERT_META[type] || { icon: "⚠️", label: type, color: "#666" };
            return `<span class="chip" style="background:${meta.color};margin-right:4px">${meta.icon} ${n}</span>`;
        })
        .join("");
}

// Tiny SVG sparkline of the node's recent water levels, from the
// telemetry history endpoint. Pure string building - no chart library.
async function loadSparkline(village, nodeId) {
    const slot = document.getElementById("spark-slot");
    if (!slot) return; // panel closed before the fetch finished

    try {
        const rows = await api(
            `/villages/${village}/nodes/${nodeId}/telemetry?param=water&limit=30`
        );
        if (!rows.length) { slot.textContent = "no water history yet"; return; }
        if (selectedKey !== nodeKey(village, nodeId)) return;

        // API returns newest-first; plot oldest -> newest
        const levels = rows.reverse().map(
            (r) => (typeof r.value === "number" ? BITS_TO_LEVEL[r.value] || 0 : 0)
        );

        const W = 300, H = 44;
        const x = (i) => (levels.length === 1 ? W / 2 : (i / (levels.length - 1)) * W);
        const y = (l) => H - 6 - (l / 3) * (H - 12);
        const points = levels.map((l, i) => `${x(i).toFixed(1)},${y(l).toFixed(1)}`).join(" ");
        const dots = levels.map((l, i) =>
            `<circle cx="${x(i).toFixed(1)}" cy="${y(l).toFixed(1)}" r="2.2" fill="${LEVEL_COLORS[l]}"/>`
        ).join("");

        slot.innerHTML =
            `<svg width="100%" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">` +
            `<polyline points="${points}" fill="none" stroke="#1976d2" stroke-width="1.5"/>` +
            dots + `</svg>`;
    } catch {
        slot.textContent = "history unavailable";
    }
}