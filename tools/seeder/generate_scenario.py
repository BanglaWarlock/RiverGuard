"""
RiverGuard scenario generator - creates the shared world.

Generates island topologies procedurally and saves scenario.json - the
single source of truth that seed_db, seed_mqtt, and simulator all read.

No geometry, no GPS: link quality (RSSI/SNR) is generated per edge,
cost is derived from quality, and routes are computed by REAL Dijkstra
over cost. The model:

    rssi_norm = (rssi - (-105)) / ((-48) - (-105))   # 0..1
    snr_norm  = (snr - 2) / (12 - 2)                 # 0..1
    goodness  = (rssi_norm + snr_norm) / 2
    cost      = 10 * (1 - goodness)                   # low = good link

Strong signal -> cheap link; Dijkstra prefers good-signal paths.

Archetypes (topology = link structure only, quality is random):
  mesh   - each node links to 3-4 random others (redundant paths)
  bridge - two clusters joined by one chokepoint node
  chain  - sequential nodes, 1-2 links each, occasional skip-link

Preview: scenario_preview.html - open in a browser. Each island drawn
as an SVG graph (links colored by RSSI), with a full route table
including TOP-3 ALTERNATIVE PATHS per destination (Yen's k-shortest,
so you can see what Dijkstra chose AND what it beat - the alternates
count itself characterizes the archetype: mesh has 3, bridge's
chokepoint has 1-2, chain mostly 1).

Running this ALWAYS regenerates (overwrites) scenario.json.
"""

import heapq
import html
import json
import math
import os
import random
import datetime

SCENARIO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "scenario.json")
PREVIEW_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "scenario_preview.html")

ISLANDS = [
    {"name": "MESH01",  "archetype": "mesh",         "nodes": 9},
    {"name": "BRDG02",  "archetype": "bridge",       "nodes": 11},
    {"name": "CHAIN03", "archetype": "chain",        "nodes": 8},
    {"name": "STAR04",  "archetype": "star",         "nodes": 10},
    {"name": "RING05",  "archetype": "ring",         "nodes": 10},
    {"name": "CLUS06",  "archetype": "cluster_pair", "nodes": 12},
]

RSSI_MIN, RSSI_MAX = -105.0, -48.0
SNR_MIN, SNR_MAX = 2.0, 12.0

BLACKLIST_TIMELINE = [
    {"day": 2, "v": 1, "sequence": 5, "edges": []},
    {"day": 3, "v": 1, "sequence": 6, "edges": []},
    {"day": 5, "v": 2, "sequence": 7, "edges": [],},
]

# --- link quality model ---

def random_link():
    """One edge: random quality, cost derived from quality."""
    rssi = round(random.uniform(RSSI_MIN, RSSI_MAX), 1)
    snr = round(random.uniform(SNR_MIN, SNR_MAX), 1)

    rssi_norm = (rssi - RSSI_MIN) / (RSSI_MAX - RSSI_MIN)
    snr_norm = (snr - SNR_MIN) / (SNR_MAX - SNR_MIN)
    goodness = (rssi_norm + snr_norm) / 2
    cost = round(10.0 * (1.0 - goodness), 1)

    return {"rssi": rssi, "snr": snr, "cost": cost}

def make_link(a_id, b_id):
    q = random_link()
    return {"a": a_id, "b": b_id, **q}

# --- archetype generators (topology only, no geometry) ---

def gen_mesh(cfg):
    """Each node links to 3-4 random others: redundant paths everywhere."""
    count = cfg["nodes"]
    ids = [f"{cfg['name']}-N{i+1:03d}" for i in range(count)]
    links = []
    for i, id_a in enumerate(ids):
        others = [nid for j, nid in enumerate(ids) if j != i]
        partners = random.sample(others, min(random.randint(3, 4), len(others)))
        for id_b in partners:
            if not any((l["a"] == id_b and l["b"] == id_a) for l in links):
                links.append(make_link(id_a, id_b))

    sta = f"{cfg['name']}-STA"
    for id_b in random.sample(ids, 2):
        links.append(make_link(sta, id_b))
    return sta, ids, links

def gen_bridge(cfg):
    """Two clusters joined by one chokepoint node: the single highway."""
    half = cfg["nodes"] // 2
    left = [f"{cfg['name']}-L{i+1:03d}" for i in range(half)]
    right = [f"{cfg['name']}-R{i+1:03d}" for i in range(cfg["nodes"] - half - 1)]
    bridge = f"{cfg['name']}-BRIDGE"

    links = []
    def connect_group(group, k_min, k_max):
        for id_a in group:
            others = [nid for nid in group if nid != id_a]
            for id_b in random.sample(others,
                                      min(random.randint(k_min, k_max), len(others))):
                if not any((l["a"] == id_b and l["b"] == id_a) for l in links):
                    links.append(make_link(id_a, id_b))

    connect_group(left, 2, 3)
    connect_group(right, 2, 3)

    # the chokepoint: bridge links to ONE node per cluster
    links.append(make_link(bridge, random.choice(left)))
    links.append(make_link(bridge, random.choice(right)))

    sta = f"{cfg['name']}-STA"
    links.append(make_link(sta, random.choice(left)))
    return sta, left + right + [bridge], links

def gen_chain(cfg):
    """Sequential nodes: 1-2 links each, occasional skip-link."""
    count = cfg["nodes"]
    ids = [f"{cfg['name']}-C{i+1:03d}" for i in range(count)]
    links = []
    for i in range(count - 1):
        links.append(make_link(ids[i], ids[i + 1]))
        if i + 2 < count and random.random() < 0.3:
            links.append(make_link(ids[i], ids[i + 2]))

    sta = f"{cfg['name']}-STA"
    links.append(make_link(sta, ids[0]))
    return sta, ids, links

def gen_star(cfg):
    """One hub node: everything connects only to it. The anti-mesh -
    total dependence on a single relay."""
    count = cfg["nodes"]
    hub = f"{cfg['name']}-HUB"
    spokes = [f"{cfg['name']}-S{i+1:03d}" for i in range(count)]
    links = [make_link(hub, s) for s in spokes]
    sta = f"{cfg['name']}-STA"
    links.append(make_link(sta, hub))
    return sta, spokes + [hub], links   # hub IS a node - include it

def gen_ring(cfg):
    """Nodes in a loop: exactly two paths between any pair, plus
    occasional chords for a third option."""
    count = cfg["nodes"]
    ids = [f"{cfg['name']}-R{i+1:03d}" for i in range(count)]
    links = []
    for i in range(count):
        links.append(make_link(ids[i], ids[(i + 1) % count]))   # the loop
    # 2-3 chords across the ring
    for _ in range(min(3, count // 3)):
        i, j = sorted(random.sample(range(count), 2))
        if not any((l["a"] == ids[i] and l["b"] == ids[j]) or
                   (l["a"] == ids[j] and l["b"] == ids[i]) for l in links):
            links.append(make_link(ids[i], ids[j]))
    sta = f"{cfg['name']}-STA"
    links.append(make_link(sta, ids[0]))
    return sta, ids, links

def gen_cluster_pair(cfg):
    """Three small clusters; each pair joined by its own bridge node.
    Cluster A reaches cluster C only THROUGH cluster B's bridge."""
    per = max(3, cfg["nodes"] // 3)
    groups = []
    idx = 0
    for g in range(3):
        ids = [f"{cfg['name']}-G{g+1}N{i+1:03d}" for i in range(per)]
        groups.append(ids)
        idx += per

    links = []
    for ids in groups:
        for id_a in ids:
            others = [nid for nid in ids if nid != id_a]
            for id_b in random.sample(others, min(2, len(others))):
                if not any((l["a"] == id_b and l["b"] == id_a) for l in links):
                    links.append(make_link(id_a, id_b))

    # one bridge node per adjacent cluster pair (G1-G2, G2-G3)
    for g in range(2):
        bridge = f"{cfg['name']}-B{g+1}"
        links.append(make_link(bridge, random.choice(groups[g])))
        links.append(make_link(bridge, random.choice(groups[g + 1])))

    sta = f"{cfg['name']}-STA"
    links.append(make_link(sta, random.choice(groups[0])))
    all_ids = [nid for ids in groups for nid in ids] + \
              [f"{cfg['name']}-B1", f"{cfg['name']}-B2"]
    return sta, all_ids, links

GENERATORS = {"mesh": gen_mesh, "bridge": gen_bridge, "chain": gen_chain,
              "star": gen_star, "ring": gen_ring, "cluster_pair": gen_cluster_pair}

# --- Dijkstra ---

def build_adjacency(links):
    """links -> {node: [(neighbor, cost, rssi, snr), ...]} bidirectional."""
    adj = {}
    for l in links:
        adj.setdefault(l["a"], []).append((l["b"], l["cost"], l["rssi"], l["snr"]))
        adj.setdefault(l["b"], []).append((l["a"], l["cost"], l["rssi"], l["snr"]))
    return adj

def dijkstra(adj, start):
    """Single-source shortest paths. Returns {dest: {next_hop, hops,
    cost, path}}. The route table each node would report."""
    dist = {start: 0.0}
    prev = {}
    visited = set()
    pq = [(0.0, start)]
    while pq:
        d, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)
        for v, cost, _, _ in adj.get(u, []):
            nd = d + cost
            if v not in dist or nd < dist[v]:
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))

    routes = {}
    for dest in dist:
        if dest == start:
            continue
        path = [dest]
        cur = dest
        while cur in prev:
            cur = prev[cur]
            path.insert(0, cur)
        routes[dest] = {"next_hop": path[1], "hops": len(path) - 1,
                         "cost": round(dist[dest], 1), "path": path}
    return routes

def compute_route_table(adj, node_id):
    """One node's full route table via Dijkstra, with first-hop link quality."""
    routes = dijkstra(adj, node_id)
    table = []
    for dest, info in routes.items():
        first_hop = info["next_hop"]
        link = next((l for l in adj.get(node_id, []) if l[0] == first_hop), None)
        table.append({
            "d": dest, "n": first_hop, "h": info["hops"],
            "c": info["cost"], "l": link[1] if link else None,
            "ri": link[2] if link else None, "sn": link[3] if link else None,
            "p": ">".join(info["path"]),
            "a": random.randint(400, 3000), "q": random.randint(10, 50),
        })
    return table

# --- Yen's k-shortest loopless paths (the ranked alternatives) ---

def _dijkstra_banned(adj, start, dest, banned):
    """Dijkstra that refuses to traverse any (a,b) pair in 'banned'.
    Returns the destination's path info or None if unreachable."""
    dist = {start: 0.0}
    prev = {}
    visited = set()
    pq = [(0.0, start)]
    while pq:
        d, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)
        for v, cost, _, _ in adj.get(u, []):
            if (u, v) in banned:
                continue
            nd = d + cost
            if v not in dist or nd < dist[v]:
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))

    if dest not in dist:
        return None
    path = [dest]
    cur = dest
    while cur in prev:
        cur = prev[cur]
        path.insert(0, cur)
    return {"path": path, "cost": dist[dest]}

def _path_cost(adj, path):
    """Total cost along an explicit path."""
    total = 0.0
    for a, b in zip(path, path[1:]):
        for v, cost, _, _ in adj.get(a, []):
            if v == b:
                total += cost
                break
    return total

def yen_k_shortest(adj, source, dest, k=3):
    """
    Top-k shortest loopless paths from source to dest (Yen's algorithm).
    Returns [{"path": [ids...], "cost": total}, ...] best-first; fewer
    if fewer distinct paths exist (chain tails, bridge chokepoints).
    Path #1 always equals plain Dijkstra's answer - self-verifying.
    """
    if source == dest:
        return []

    best = dijkstra(adj, source).get(dest)
    if best is None:
        return []

    A = [{"path": best["path"], "cost": best["cost"]}]
    candidates = []   # (cost, path) - deduped, sorted on use

    for _ in range(k - 1):
        prev_path = A[-1]["path"]
        for i in range(len(prev_path) - 1):
            spur_node = prev_path[i]
            root = prev_path[:i + 1]

            # ban edges that parallel already-accepted roots
            banned = set()
            for accepted in A:
                if accepted["path"][:i + 1] == root:
                    p = accepted["path"]
                    banned.add((p[i], p[i + 1]))
                    banned.add((p[i + 1], p[i]))

            spur = _dijkstra_banned(adj, spur_node, dest, banned)
            if spur is None:
                continue

            total_path = root[:-1] + spur["path"]
            # loopless + not already found
            if len(set(total_path)) != len(total_path):
                continue
            if any(c[1] == total_path for c in candidates):
                continue
            if any(a["path"] == total_path for a in A):
                continue

            root_cost = _path_cost(adj, root)
            candidates.append((root_cost + spur["cost"], total_path))

        if not candidates:
            break
        candidates.sort(key=lambda c: c[0])
        cost, path = candidates.pop(0)
        A.append({"path": path, "cost": round(cost, 1)})

    return A

# --- connectivity check (with repair pass) ---

def ensure_connected(adj, sta, all_ids):
    """Any unreachable node gets one link to a random reachable node.
    Returns the extra links added."""
    extras = []
    while True:
        reachable = set(dijkstra(adj, sta).keys()) | {sta}
        unreachable = [i for i in all_ids if i not in reachable]
        if not unreachable:
            return extras
        node = unreachable[0]
        target = random.choice(sorted(reachable))
        link = make_link(node, target)
        extras.append(link)
        adj.setdefault(node, []).append((target, link["cost"], link["rssi"], link["snr"]))
        adj.setdefault(target, []).append((node, link["cost"], link["rssi"], link["snr"]))

# --- preview HTML ---

def link_color(rssi):
    if rssi > -70: return "#43a047"
    if rssi > -85: return "#fb8c00"
    return "#e53935"

def _short(nid):
    """Last segment of a node id: MESH01-N003 -> N003."""
    return nid.split("-")[-1]

def build_preview(scenario, route_tables):
    """Self-contained interactive HTML:
    - tabs per island
    - SVG graph per island; hover a node -> its destination list
    - route explorer: select start -> select end (from that node's
      actual destinations) -> top-3 paths (Yen) shown, others dimmed
      (toggleable); 'animate path' marches the chosen path's edges,
      flowing start -> end (edges are re-oriented to the path's
      direction before animating).
    """

    # --- build the data payload once (all islands) ---
    payload = []
    for island in scenario["islands"]:
        adj = build_adjacency(island["links"])
        paths = {}
        for nid in [island["station"]] + island["nodes"]:
            for rt in route_tables.get(nid, []):
                paths[f"{nid}>{rt['d']}"] = [
                    {"path": p["path"], "cost": p["cost"]}
                    for p in yen_k_shortest(adj, nid, rt["d"], k=3)]
        payload.append({
            "name": island["name"], "archetype": island["archetype"],
            "station": island["station"], "nodes": island["nodes"],
            "links": island["links"],
            "routes": route_tables,
            "paths": paths,
        })

    data_json = json.dumps(payload)

    doc = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>RiverGuard scenario preview</title><style>
body { font-family: system-ui; margin: 0; background: #f4f7f9; color: #222; }
header { background: #14324f; color: #fff; padding: 10px 24px; }
header h1 { font-size: 18px; margin: 0; } header p { font-size: 12px; opacity: .7; margin: 2px 0 0; }
.tabs { display: flex; gap: 4px; background: #fff; padding: 6px 24px;
        border-bottom: 1px solid #dde; flex-wrap: wrap; }
.tab { padding: 8px 14px; cursor: pointer; font-size: 14px; color: #666;
       border-bottom: 2px solid transparent; }
.tab.active { color: #0f6e84; border-bottom-color: #0f6e84; font-weight: 600; }
.island { display: none; padding: 24px; }
.island.active { display: block; }
.island-box { background: #fff; border: 1px solid #dde; border-radius: 8px;
              padding: 20px; }
h2 { color: #14324f; margin: 0 0 4px; } .tag { font-size: 12px; color: #888; font-weight: normal; }
.meta { color: #666; font-size: 13px; margin-bottom: 16px; }
.svgwrap { position: relative; }
.node-info { position: absolute; top: 8px; right: 8px; background: #fff;
            border: 1px solid #dde; border-radius: 6px; padding: 10px 12px;
            font-size: 12px; display: none; max-width: 260px; z-index: 5; }
.node-info b { color: #14324f; }
.node-info ul { margin: 4px 0 0 16px; padding: 0; }
.explorer { margin-top: 20px; padding-top: 16px; border-top: 1px solid #eee; }
.explorer label { font-size: 13px; margin-right: 12px; }
.explorer select { padding: 4px 8px; margin-right: 16px; font-size: 13px; }
.explorer .anim { font-size: 13px; }
.paths { margin-top: 12px; }
.path-opt { display: flex; align-items: center; gap: 10px; padding: 6px 10px;
           border: 1px solid #e0e6ec; border-radius: 6px; margin-bottom: 6px;
           font-size: 13px; cursor: pointer; }
.path-opt.selected { background: #e0f2f5; border-color: #0f6e84; }
.path-opt .cost { color: #0f6e84; font-weight: 600; }
.path-opt .route { color: #555; }
.none { font-size: 13px; color: #888; font-style: italic; }
text { font-family: system-ui; }
.dim { opacity: 0.15; }
.onpath { animation: march 0.9s linear infinite; }
@keyframes march { to { stroke-dashoffset: -28; } }
</style></head><body>
<header><h1>RiverGuard scenario preview</h1>
<p>Generated world - topology, links, and real Dijkstra/Yen routing. Hover nodes; explore routes.</p></header>
<div class="tabs" id="tabs"></div>
<div id="islands"></div>
<script>
const DATA = __PAYLOAD__;

// declared BEFORE the render loop: the initial cascade (fired during
// build) reads this - declaring it below caused a TDZ ReferenceError
let currentPath = {};   // island -> selected path

const tabsEl = document.getElementById('tabs');
const islandsEl = document.getElementById('islands');

DATA.forEach((isl, i) => {
  const t = document.createElement('div');
  t.className = 'tab' + (i === 0 ? ' active' : '');
  t.textContent = isl.name + ' (' + isl.archetype + ')';
  t.onclick = () => {
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    document.querySelectorAll('.island').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    document.getElementById('isl-' + i).classList.add('active');
  };
  tabsEl.appendChild(t);

  const panel = document.createElement('div');
  panel.className = 'island' + (i === 0 ? ' active' : '');
  panel.id = 'isl-' + i;
  panel.innerHTML = `
    <div class="island-box">
      <h2>${isl.name} <span class="tag">${isl.archetype}</span></h2>
      <div class="meta">${isl.nodes.length} nodes + station, ${isl.links.length} links</div>
      <div class="svgwrap" id="wrap-${i}"></div>
      <div class="node-info" id="info-${i}"></div>
      <div class="explorer">
        <label>start:</label><select id="start-${i}"></select>
        <label>end:</label><select id="end-${i}"></select>
        <label class="anim"><input type="checkbox" id="dim-${i}" checked> dim others</label>
        <label class="anim"><input type="checkbox" id="anim-${i}"> animate path</label>
        <div class="paths" id="paths-${i}"></div>
      </div>
    </div>`;
  islandsEl.appendChild(panel);
  buildGraph(i, isl);
  buildExplorer(i, isl);
});

function short(nid) { return nid.split('-').slice(1).join('-') || nid; }
function linkColor(rssi) {
  if (rssi > -70) return '#43a047';
  if (rssi > -85) return '#fb8c00';
  return '#e53935';
}

function buildGraph(i, isl) {
  const wrap = document.getElementById('wrap-' + i);
  const ids = [isl.station].concat(isl.nodes);
  const n = ids.length, cx = 220, cy = 220, r = 130 + n * 4;
  const pos = {};
  ids.forEach((nid, j) => {
    const a = (j / n) * 2 * Math.PI - Math.PI / 2;
    pos[nid] = [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  });

  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('width', 440); svg.setAttribute('height', 440);
  svg.setAttribute('viewBox', '0 0 440 440');

// edges - skip (with warning) any link referencing an unknown node
  isl.links.forEach(l => {
    if (!pos[l.a] || !pos[l.b]) {
      console.warn('link references unknown node:', l.a, l.b);
      return;
    }
    const ln = document.createElementNS(NS, 'line');
    ln.setAttribute('x1', pos[l.a][0]); ln.setAttribute('y1', pos[l.a][1]);
    ln.setAttribute('x2', pos[l.b][0]); ln.setAttribute('y2', pos[l.b][1]);
    ln.setAttribute('stroke', linkColor(l.rssi));
    ln.setAttribute('stroke-width', 2);
    ln.setAttribute('class', 'edge');
    ln.dataset.a = l.a; ln.dataset.b = l.b;
    ln.dataset.rssi = l.rssi; ln.dataset.snr = l.snr;
    // original endpoints, stored once: path animation swaps x1/x2 to
    // orient the marching dashes, and clearHighlight restores from these
    ln.dataset.ox1 = pos[l.a][0]; ln.dataset.oy1 = pos[l.a][1];
    ln.dataset.ox2 = pos[l.b][0]; ln.dataset.oy2 = pos[l.b][1];
    svg.appendChild(ln);
  });

  // nodes
  const info = document.getElementById('info-' + i);
  ids.forEach(nid => {
    const g = document.createElementNS(NS, 'g');
    g.dataset.id = nid;
    const c = document.createElementNS(NS, 'circle');
    const isSta = nid === isl.station;
    c.setAttribute('cx', pos[nid][0]); c.setAttribute('cy', pos[nid][1]);
    c.setAttribute('r', isSta ? 13 : 10);
    c.setAttribute('fill', isSta ? '#3949ab' : '#fff');
    c.setAttribute('stroke', '#14324f');
    c.setAttribute('stroke-width', 2);
    const tx = document.createElementNS(NS, 'text');
    tx.setAttribute('x', pos[nid][0]);
    tx.setAttribute('y', pos[nid][1] + 32);
    tx.setAttribute('text-anchor', 'middle');
    tx.setAttribute('font-size', 9);
    tx.setAttribute('fill', '#333');
    tx.textContent = short(nid);
    g.appendChild(c); g.appendChild(tx);

    g.onmouseenter = () => {
      const routes = isl.routes[nid] || [];
      info.innerHTML = `<b>${nid}</b><br>` +
        `links: ${isl.links.filter(l => l.a === nid || l.b === nid).length} · ` +
        `destinations: ${routes.length}` +
        (routes.length ? `<ul>` +
          routes.map(r => `<li>${short(r.d)} (${r.c})</li>`).join('') + `</ul>`
        : `<br><i>knows no routes (isolated or is the only node)</i>`);
      info.style.display = 'block';
    };
    g.onmouseleave = () => { info.style.display = 'none'; };
    g.onclick = () => {
      const sel = document.getElementById('start-' + i);
      if (![...sel.options].some(o => o.value === nid)) return;
      sel.value = nid;
      sel.dispatchEvent(new Event('change'));
    };
    svg.appendChild(g);
  });

  wrap.appendChild(svg);
}

function buildExplorer(i, isl) {
  const startSel = document.getElementById('start-' + i);
  const endSel = document.getElementById('end-' + i);
  const pathsEl = document.getElementById('paths-' + i);
  const animChk = document.getElementById('anim-' + i);
  const dimChk = document.getElementById('dim-' + i);
  const allIds = [isl.station].concat(isl.nodes);

  // start options: any node with at least one destination
  const routed = allIds.filter(nid => (isl.routes[nid] || []).length > 0);
  routed.forEach(nid => {
    const o = document.createElement('option');
    o.value = nid; o.textContent = short(nid);
    startSel.appendChild(o);
  });
  if (!routed.length) {
    pathsEl.innerHTML = '<span class="none">no routes exist in this island</span>';
    return;
  }

  startSel.onchange = () => {
    // end options come from THIS node's destinations
    endSel.innerHTML = '';
    const routes = isl.routes[startSel.value] || [];
    routes.forEach(rt => {
      const o = document.createElement('option');
      o.value = rt.d; o.textContent = short(rt.d);
      endSel.appendChild(o);
    });
    clearHighlight(i);
    if (routes.length) {
      endSel.dispatchEvent(new Event('change'));
    } else {
      pathsEl.innerHTML = '<span class="none">this node knows no routes (isolated)</span>';
    }
  };

  endSel.onchange = () => {
    pathsEl.innerHTML = '';
    const key = startSel.value + '>' + endSel.value;
    const paths = isl.paths[key] || [];

    paths.forEach(p => {
      const row = document.createElement('div');
      row.className = 'path-opt';
      row.innerHTML =
        `<span class="cost">${p.cost}</span>` +
        `<span class="route">${p.path.map(short).join(' &gt; ')}</span>`;
      row.onclick = () => {
        document.querySelectorAll('#paths-' + i + ' .path-opt')
          .forEach(x => x.classList.remove('selected'));
        row.classList.add('selected');
        highlightPath(i, p.path, animChk.checked, dimChk.checked);
      };
      pathsEl.appendChild(row);
    });
    if (paths.length) {
      pathsEl.querySelector('.path-opt').click();   // auto-select path #1
    } else {
      pathsEl.innerHTML = '<span class="none">no paths found</span>';
    }
  };

  // both toggles re-render the current path with their new state
  const reRender = () => {
    if (currentPath[i])
      highlightPath(i, currentPath[i], animChk.checked, dimChk.checked);
  };
  animChk.onchange = reRender;
  dimChk.onchange = reRender;

  // fire the cascade once on build: the browser auto-selects option 0,
  // so the initial state is consistent (start -> ends -> path #1)
  startSel.dispatchEvent(new Event('change'));
}

function clearHighlight(i) {
  const panel = document.getElementById('isl-' + i);
  panel.querySelectorAll('.edge').forEach(ln => {
    ln.classList.remove('dim', 'onpath');
    ln.removeAttribute('stroke-dasharray');
    ln.setAttribute('stroke-width', 2);
    ln.setAttribute('stroke', linkColor(parseFloat(ln.dataset.rssi)));
    // restore the original endpoints: a previous path's animation may
    // have swapped them, and every highlight decision must start from
    // the true link direction (this was the stale-orientation bug)
    if (ln.dataset.ox1 !== undefined) {
      ln.setAttribute('x1', ln.dataset.ox1);
      ln.setAttribute('y1', ln.dataset.oy1);
      ln.setAttribute('x2', ln.dataset.ox2);
      ln.setAttribute('y2', ln.dataset.oy2);
    }
  });
  panel.querySelectorAll('g').forEach(g => g.classList.remove('dim'));
  currentPath[i] = null;
}

function highlightPath(i, path, animate, dimOthers) {
  if (!path) return;
  clearHighlight(i);
  currentPath[i] = path;

  const panel = document.getElementById('isl-' + i);
  const onPath = new Set(path);
  const pathEdges = [];   // [{el, index}] - index = position in the path

  panel.querySelectorAll('.edge').forEach(ln => {
    // an edge is on the path only if it connects CONSECUTIVE path
    // nodes; remember WHERE (j) so animation can orient correctly
    let found = -1;
    for (let j = 0; j < path.length - 1; j++) {
      if ((path[j] === ln.dataset.a && path[j + 1] === ln.dataset.b) ||
          (path[j] === ln.dataset.b && path[j + 1] === ln.dataset.a)) {
        found = j; break;
      }
    }
    if (found >= 0) pathEdges.push({el: ln, index: found});
    else if (dimOthers) ln.classList.add('dim');
  });
  panel.querySelectorAll('g').forEach(g => {
    if (!onPath.has(g.dataset.id) && dimOthers) g.classList.add('dim');
  });

  pathEdges.forEach(({el, index}) => {
    el.setAttribute('stroke', '#0f6e84');
    el.setAttribute('stroke-width', 4);
    if (animate) {
      // SVG dash animation flows from (x1,y1) to (x2,y2). Lines were
      // drawn in LINK direction, which may oppose the PATH direction
      // through that edge - swap endpoints so the march always flows
      // start -> end. (Plain lines have no visible direction, so the
      // swap is invisible once the animation is cleared.)
      if (el.dataset.a !== path[index]) {
        const x1 = el.getAttribute('x1'), y1 = el.getAttribute('y1');
        el.setAttribute('x1', el.getAttribute('x2'));
        el.setAttribute('y1', el.getAttribute('y2'));
        el.setAttribute('x2', x1); el.setAttribute('y2', y1);
      }
      el.setAttribute('stroke-dasharray', '8 6');
      el.classList.add('onpath');
    }
  });
}
</script>
</body></html>"""

    doc = doc.replace("__PAYLOAD__", data_json)
    with open(PREVIEW_FILE, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"[gen] preview saved: {PREVIEW_FILE} (interactive)")

# --- main ---

def generate():
    random.seed()   # a new world every run
    scenario = {
        "generated": datetime.datetime.utcnow().isoformat(),
        "islands": [],
    }
    route_tables = {}

    for cfg in ISLANDS:
        sta, ids, links = GENERATORS[cfg["archetype"]](cfg)

        # connectivity: repair any disconnected nodes
        adj = build_adjacency(links)
        extras = ensure_connected(adj, sta, ids)
        if extras:
            print(f"[gen] {cfg['name']}: repaired {len(extras)} disconnected node(s)")
            links += extras
            adj = build_adjacency(links)

        # verify
        reachable = set(dijkstra(adj, sta).keys()) | {sta}
        assert all(i in reachable for i in ids), "connectivity repair failed"

        # compute all route tables (real Dijkstra)
        for nid in [sta] + ids:
            route_tables[nid] = compute_route_table(adj, nid)

        scenario["islands"].append({
            "name": cfg["name"], "archetype": cfg["archetype"],
            "station": sta, "nodes": ids, "links": links,
        })
        print(f"[gen] {cfg['name']} ({cfg['archetype']}): "
              f"{len(ids)} nodes, {len(links)} links, station {sta}")

    _fill_blacklist(scenario)

    with open(SCENARIO_FILE, "w") as f:
        json.dump(scenario, f, indent=2)
    print(f"\n[gen] scenario saved: {SCENARIO_FILE}")

    build_preview(scenario, route_tables)

def _fill_blacklist(scenario):
    """Pick real edges from the topology for the blacklist story."""
    islands = scenario["islands"]
    mesh = next(i for i in islands if i["archetype"] == "mesh")
    chain = next(i for i in islands if i["archetype"] == "chain")

    if mesh["links"]:
        link = random.choice(mesh["links"])
        BLACKLIST_TIMELINE[0]["edges"] = [[link["a"], link["b"]]]
    if chain["links"]:
        link = random.choice(chain["links"])
        BLACKLIST_TIMELINE[1]["edges"] = BLACKLIST_TIMELINE[0]["edges"] + \
            [[link["a"], link["b"]]]
    BLACKLIST_TIMELINE[2]["edges"] = BLACKLIST_TIMELINE[0]["edges"]
    scenario["blacklist_timeline"] = BLACKLIST_TIMELINE

def load():
    """Load the scenario file (generate if missing)."""
    if not os.path.exists(SCENARIO_FILE):
        print("[scenario] not found - generating")
        generate()
    with open(SCENARIO_FILE) as f:
        return json.load(f)

if __name__ == "__main__":
    generate()