function renderSideCard() {
    const el = document.getElementById("side-content");
    if (!selectedNode) {
        el.innerHTML = `<p class="none">Click a node to see its details.</p>`;
        return;
    }
    const n = meshNodes[selectedNode];
    const f = floodLevels[selectedNode];

    if (sideTab === "network") {
        const routes = routesByNode[selectedNode]?.r || [];
        const routeRows = routes.map(r =>
            `<tr><td>${r.d}</td><td>${r.n}</td><td>${r.h}</td>
       <td style="color:${linkColor(r.ri)}">${r.ri ?? "null"}</td></tr>`).join("");
        el.innerHTML = `
      <dl>
        <dt>Node</dt><dd>${selectedNode}</dd>
        <dt>Last seen</dt><dd>${n?.last_seen ? new Date(n.last_seen).toLocaleString() : "—"}</dd>
        <dt>Uptime</dt><dd>${latestTelemetry(selectedNode, "uptime_minute") ?? "—"} min</dd>
        <dt>Spreading factor</dt><dd>${latestTelemetry(selectedNode, "sf") ?? "—"}</dd>
        <dt>Tx / Rx packets</dt><dd>${latestTelemetry(selectedNode, "tx_packets") ?? "—"} / ${latestTelemetry(selectedNode, "rx_packets") ?? "—"}</dd>
      </dl>
      <h3 style="margin:14px 0 6px;font-size:12px;color:var(--muted);text-transform:uppercase">Routes</h3>
      ${routes.length ? `<table class="mini">
        <tr><th>dest</th><th>next hop</th><th>hops</th><th>RSSI</th></tr>${routeRows}</table>`
                : `<p class="none">No route reports yet.</p>`}`;
    } else {
        const v = f?.value;
        const cls = v == null ? null : floodClass(v);
        el.innerHTML = `
      <dl>
        <dt>Node</dt><dd>${selectedNode}</dd>
        <dt>Water level</dt><dd>${v == null
                ? `<span class="none">no data</span>`
                : `<span class="flood-class" style="background:${cls.color}">${cls.label}</span> (${(v * 100).toFixed(0)}%)`}</dd>
        <dt>Source</dt><dd>${v == null ? "—" : "local demo data (browser)"}</dd>
      </dl>
      <p class="none" style="margin-top:12px">Flood values are set in the Flood Edit tab.
      When hardware reports them, they will appear here from the live feed.</p>`;
    }
}

// helper: latest value of a telemetry field for a node, from API-loaded
// snapshot (stored on load; for live, stream events update meshNodes)
function latestTelemetry(nodeId, field) {
  return meshNodes[nodeId]?.[field] ?? null;
}