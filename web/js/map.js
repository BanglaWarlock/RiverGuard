// Everything Leaflet: the map, node markers, master markers,
// and the mesh lines between children and parents.
// A developer changing how the map LOOKS edits only this file.

let map;                // the Leaflet map
let lineLayer;          // holds all mesh lines, redrawn on changes
const markers = {};      // "village/nodeId" -> node circle marker
const masterMarkers = {}; // villageId -> master marker

// RSSI of a node's link to its parent -> line color
function linkColor(rssi) {
    if (rssi == null) return "#b0bec5";
    if (rssi > RSSI_GOOD) return "#43a047";
    if (rssi > RSSI_OK) return "#fb8c00";
    return "#e53935";
}

function markerStyle(node) {
    const online = node.status !== "offline";
    const level = node.water_level || 0;
    return {
        radius: 8,
        color: online ? "#37474f" : "#90a4ae",
        weight: 1.5,
        fillColor: online ? LEVEL_COLORS[level] : "#78909c",
        fillOpacity: online ? 0.95 : 0.35,
    };
}

function renderMarkers() {
    for (const key of Object.keys(nodes)) {
        const node = nodes[key];
        if (node.coordinates == null) continue;
        const pos = [node.coordinates.lat, node.coordinates.lng];
        if (markers[key]) { markers[key].setLatLng(pos); updateMarker(...key.split("/")); }
        else createMarker(key, node, pos);
    }
    renderMasterMarkers();
}

function createMarker(key, node, pos) {
    const m = L.circleMarker(pos, markerStyle(node)).addTo(map);
    m.bindTooltip("");
    m.on("click", () => selectNode(key));
    markers[key] = m;
    updateMarker(node.village_id, node.node_id);
}

function updateMarker(village, nodeId) {
    const key = nodeKey(village, nodeId);
    const node = nodes[key];
    const m = markers[key];
    if (!node || !m) return;

    m.setStyle(markerStyle(node));
    m.setTooltipContent(
        `<b>${nodeId}</b> · ${LEVEL_LABELS[node.water_level || 0]} · ` +
        `${node.bat != null ? node.bat.toFixed(1) + "V" : "?"}` +
        (node.rssi != null ? ` · link ${node.rssi} dBm → ${node.parent_id || "?"}` : "")
    );
}

function flashNode(village, nodeId) {
    const m = markers[nodeKey(village, nodeId)];
    if (!m) return;
    m.setStyle({ radius: 13, weight: 3, color: "#fff" });
    setTimeout(() => {
        const node = nodes[nodeKey(village, nodeId)];
        if (node) m.setStyle(markerStyle(node));
    }, 1500);
}

// Master nodes have no GPS - place a marker at the center of their
// village's nodes so the mesh root is visible on the map.
function renderMasterMarkers() {
    for (const id of Object.keys(villages)) {
        const vNodes = Object.values(nodes).filter(
            (n) => n.village_id === id && n.coordinates
        );
        if (!vNodes.length) continue;
        const center = [
            vNodes.reduce((s, n) => s + n.coordinates.lat, 0) / vNodes.length,
            vNodes.reduce((s, n) => s + n.coordinates.lng, 0) / vNodes.length,
        ];

        const v = villages[id];
        const online = v && v.is_online;

        if (masterMarkers[id]) {
            masterMarkers[id].setLatLng(center);
            masterMarkers[id].setStyle({
                fillColor: online ? "#3949ab" : "#9fa8da", fillOpacity: online ? 0.9 : 0.4,
            });
        } else {
            const m = L.circleMarker(center, {
                radius: 11, color: "#1a237e", weight: 2,
                fillColor: online ? "#3949ab" : "#9fa8da",
                fillOpacity: online ? 0.9 : 0.4,
            }).addTo(map);
            m.bindTooltip(`<b>${id} master</b> (${v.master_id || "?"})`);
            m.on("click", () => flyToVillage(id));
            masterMarkers[id] = m;
        }
    }
}

// Mesh lines: child -> its parent (master or another node),
// colored by the child's rssi (link quality to that parent).
function renderLines() {
    if (!lineLayer) lineLayer = L.layerGroup().addTo(map);
    lineLayer.clearLayers();

    for (const node of Object.values(nodes)) {
        if (!node.coordinates || !node.parent_id) continue;

        let parentPos = null;
        const parentNode = nodes[nodeKey(node.village_id, node.parent_id)];
        if (parentNode && parentNode.coordinates)
            parentPos = [parentNode.coordinates.lat, parentNode.coordinates.lng];
        else if (masterMarkers[node.village_id])
            parentPos = masterMarkers[node.village_id].getLatLng();

        if (!parentPos) continue; // parent coords unknown (or orphan node)

        L.polyline(
            [[node.coordinates.lat, node.coordinates.lng], parentPos],
            { color: linkColor(node.rssi), weight: 2, opacity: 0.85 }
        ).addTo(lineLayer);
    }
}

function flyToVillage(id) {
    const vNodes = Object.values(nodes).filter(
        (n) => n.village_id === id && n.coordinates
    );
    if (!vNodes.length) return;
    const bounds = L.latLngBounds(
        vNodes.map((n) => [n.coordinates.lat, n.coordinates.lng])
    );
    map.flyToBounds(bounds, { padding: [60, 60] });
}