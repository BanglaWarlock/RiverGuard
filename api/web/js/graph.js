// The network canvas: SVG, pan by dragging background, zoom by wheel,
// nodes draggable (positions persisted to localStorage), edges from
// route reports. Node color = status, edge color = link quality.

let svg, gWorld, gEdges, gNodes;      // svg structure
let view = { x: 0, y: 0, k: 1 };      // pan/zoom transform
let tipEl = null;

const POS_KEY = "rg_graph_positions";

function graphInit() {
    const host = document.getElementById("graph-canvas");
    svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    host.appendChild(svg);
    gEdges = group("edges"); gNodes = group("nodes");
    gWorld = group("world");
    svg.appendChild(gWorld);
    gWorld.appendChild(gEdges); gWorld.appendChild(gNodes);

    tipEl = document.createElement("div");
    tipEl.className = "graph-tip";
    tipEl.style.display = "none";
    host.appendChild(tipEl);

    renderLegend();

    // pan: drag on empty canvas
    let panning = null;
    host.addEventListener("mousedown", e => {
        if (e.target === svg || e.target === gWorld) {
            panning = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
            host.classList.add("dragging");
        }
    });
    window.addEventListener("mousemove", e => {
        if (panning) {
            view.x = panning.vx + (e.clientX - panning.x);
            view.y = panning.vy + (e.clientY - panning.y);
            applyView();
        }
    });
    window.addEventListener("mouseup", () => { panning = null; host.classList.remove("dragging"); });

    // zoom: wheel
    host.addEventListener("wheel", e => {
        e.preventDefault();
        const f = e.deltaY < 0 ? 1.15 : 1 / 1.15;
        view.k = Math.min(4, Math.max(0.2, view.k * f));
        applyView();
    }, { passive: false });
}

function group(cls) {
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.setAttribute("class", cls);
    return g;
}

// node visual status from its data (colors explained in the legend)
function nodeStatus(id) {
    const n = meshNodes[id];
    if (!n?.last_seen) return "unknown";
    const ageMin = (Date.now() - new Date(n.last_seen)) / 60000;
    if (ageMin > 15) return "stale";        // matches /stats' window
    if (n.sf >= 11) return "struggling";     // high SF = weak link
    return "healthy";
}

function statusStroke(status) {
    return {
        healthy: "var(--primary)",
        struggling: "var(--level1)",
        stale: "var(--muted)",
        unknown: "var(--link-none)"
    }[status] || "var(--primary)";
}

function renderLegend() {
    const host = document.getElementById("graph-canvas");
    const legend = document.createElement("div");
    legend.id = "graph-legend";
    legend.innerHTML =
        `<div class="lg-title">nodes</div>` +
        `<div><span class="lg-swatch" style="background:var(--primary)"></span>healthy</div>` +
        `<div><span class="lg-swatch" style="background:var(--level1)"></span>high SF (weak)</div>` +
        `<div><span class="lg-swatch" style="background:var(--muted)"></span>quiet &gt;15 min</div>` +
        `<div class="lg-title">links</div>` +
        `<div><span class="lg-line" style="background:var(--link-good)"></span>strong</div>` +
        `<div><span class="lg-line" style="background:var(--link-mid)"></span>fair</div>` +
        `<div><span class="lg-line" style="background:var(--link-bad)"></span>weak</div>` +
        `<div><span class="lg-line lg-dashed"></span>blacklisted</div>`;
    host.appendChild(legend);
}

// --- node positions: saved layout, else auto circle ---
function loadPositions() {
    try { return JSON.parse(localStorage.getItem(POS_KEY) || "{}"); }
    catch { return {}; }
}
function savePositions(p) { localStorage.setItem(POS_KEY, JSON.stringify(p)); }

function nodePosition(id, positions, count, i) {
    if (positions[id]) return positions[id];
    const r = 180 + count * 6;
    const a = (i / Math.max(count, 1)) * Math.PI * 2 - Math.PI / 2;
    return { x: 400 + r * Math.cos(a), y: 320 + r * Math.sin(a) };
}

// --- main render: nodes + edges from route reports ---
function graphRender() {
    const ids = Object.keys(meshNodes);
    const positions = loadPositions();

    gNodes.innerHTML = ""; gEdges.innerHTML = "";
    const positionsOut = { ...positions };

    // edges: from each node's newest route report (route "n" = next hop)
    const edges = {};
    ids.forEach(id => {
        const routes = routesByNode[id]?.r || [];
        routes.forEach(rt => {
            if (rt.n && rt.n !== id) {
                const key = [id, rt.n].sort().join("~");
                if (!edges[key]) edges[key] = {
                    from: id, to: rt.n,
                    ri: rt.ri, sn: rt.sn, h: rt.h, c: rt.c
                };
            }
        });
    });

    // draw edges
    Object.values(edges).forEach(e => {
        const a = positionOf(e.from, ids, positions), b = positionOf(e.to, ids, positions);
        if (!a || !b) return;
        const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
        line.setAttribute("x1", a.x); line.setAttribute("y1", a.y);
        line.setAttribute("x2", b.x); line.setAttribute("y2", b.y);
        line.setAttribute("class", "edge");
        line.setAttribute("stroke", linkColor(e.ri));
        line.setAttribute("stroke-dasharray", isBlacklisted(e.from, e.to) ? "6 6" : null);
        line.dataset.from = e.from; line.dataset.to = e.to;
        line.addEventListener("mousemove", ev => showEdgeTip(ev, e));
        line.addEventListener("mouseleave", hideTip);
        gEdges.appendChild(line);
    });

    // draw nodes
    ids.forEach((id, i) => {
        const pos = nodePosition(id, positions, ids.length, i);
        positionsOut[id] = pos;
        const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
        g.setAttribute("class", "node" + (selectedNode === id ? " selected" : ""));
        g.dataset.id = id;

        const status = nodeStatus(id);
        const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        circle.setAttribute("cx", pos.x); circle.setAttribute("cy", pos.y); circle.setAttribute("r", 22);
        circle.setAttribute("fill", "var(--panel)");
        circle.setAttribute("stroke", statusStroke(status));
        if (status === "stale") circle.setAttribute("fill-opacity", "0.45");

        const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
        label.setAttribute("x", pos.x); label.setAttribute("y", pos.y + 4);
        label.setAttribute("text-anchor", "middle");
        label.textContent = id.slice(-4);
        g.appendChild(circle); g.appendChild(label);

        g.addEventListener("mousemove", ev => showNodeTip(ev, id));
        g.addEventListener("mouseleave", hideTip);
        g.addEventListener("click", () => { selectedNode = id; graphRender(); renderSideCard(); });

        // drag: move node, persist
        let drag = null;
        g.addEventListener("mousedown", ev => {
            ev.stopPropagation();
            drag = { dx: ev.clientX, dy: ev.clientY, ox: pos.x, oy: pos.y };
            const move = e2 => {
                if (Math.abs(e2.clientX - drag.dx) > 3 || Math.abs(e2.clientY - drag.dy) > 3)
                    drag.moved = true;
                if (!drag.moved) return;
                const k = view.k;
                pos.x = drag.ox + (e2.clientX - drag.dx) / k;
                pos.y = drag.oy + (e2.clientY - drag.dy) / k;
                circle.setAttribute("cx", pos.x); circle.setAttribute("cy", pos.y);
                label.setAttribute("x", pos.x); label.setAttribute("y", pos.y + 4);
                graphRenderEdgesOnly(ids, positions);
            };
            const up = () => {
                window.removeEventListener("mousemove", move);
                window.removeEventListener("mouseup", up);
                positionsOut[id] = pos;
                savePositions(positionsOut);
                graphRender();
            };
            window.addEventListener("mousemove", move);
            window.addEventListener("mouseup", up);
        });

        gNodes.appendChild(g);
    });
}

function positionOf(id, ids, positions) {
    const i = ids.indexOf(id);
    if (i < 0) return null;
    return nodePosition(id, positions, ids.length, i);
}

function isBlacklisted(a, b) {
    if (!activeBlacklist?.edges) return false;
    return activeBlacklist.edges.some(e =>
        (e[0] === a && e[1] === b) || (e[0] === b && e[1] === a));
}

// --- tooltips ---
function showNodeTip(ev, id) {
    const n = meshNodes[id];
    const rts = routesByNode[id]?.r || [];
    const firstHop = rts.find(r => r.ri != null);
    tipEl.innerHTML =
        `<b>${id}</b><br>` +
        `last seen: ${n?.last_seen ? new Date(n.last_seen).toLocaleTimeString() : "?"}<br>` +
        `sf: ${latestTelemetry(id, "sf") ?? "?"} · up ${latestTelemetry(id, "uptime_minute") ?? "?"}m<br>` +
        `first-hop RSSI: ${firstHop?.ri ?? "null"} dBm · SNR ${firstHop?.sn ?? "null"}`;
    showTip(ev);
}
function showEdgeTip(ev, e) {
    tipEl.innerHTML =
        `<b>${e.from} → ${e.to}</b><br>` +
        `RSSI: ${e.ri ?? "null"} dBm · SNR: ${e.sn ?? "null"}<br>` +
        `hops: ${e.h ?? "?"} · cost: ${e.c ?? "?"}` +
        (isBlacklisted(e.from, e.to) ? "<br><b>BLACKLISTED</b>" : "");
    showTip(ev);
}
function showTip(ev) {
    const host = document.getElementById("graph-canvas").getBoundingClientRect();
    tipEl.style.display = "block";
    tipEl.style.left = (ev.clientX - host.left + 14) + "px";
    tipEl.style.top = (ev.clientY - host.top + 10) + "px";
}
function hideTip() { tipEl.style.display = "none"; }

function applyView() {
    gWorld.setAttribute("transform",
        `translate(${view.x},${view.y}) scale(${view.k})`);
}

// refresh edges during a node drag without a full redraw
function graphRenderEdgesOnly(ids, positions) {
    const circles = {};
    gNodes.querySelectorAll("g.node").forEach(g => {
        const c = g.querySelector("circle");
        circles[g.dataset.id] = { x: +c.getAttribute("cx"), y: +c.getAttribute("cy") };
    });
    gEdges.querySelectorAll("line.edge").forEach(line => {
        const a = circles[line.dataset.from], b = circles[line.dataset.to];
        if (a && b) {
            line.setAttribute("x1", a.x); line.setAttribute("y1", a.y);
            line.setAttribute("x2", b.x); line.setAttribute("y2", b.y);
        }
    });
}