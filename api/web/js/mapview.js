// The Map tab: Leaflet map of positioned nodes. Markers colored by
// flood class, draggable to adjust position (localStorage). Edges
// drawn DIRECTIONALLY from route reports: A->B and B->A are separate
// curved lines (each side's own view of the link), colored by RSSI.
// Click a node/edge to highlight its routes, dim the rest, animate
// flow direction - the scenario-preview pattern, now on real data.

var mapObj, mapNodeLayer, mapEdgeLayer;
var mapEdges = [];        // [{a, b, rssi, snr, line}]
var mapHighlighted = null; // {nodeId} or {a, b}

function mapInit() {
    mapObj = L.map("map");
    mapObj.setView(MAP_CENTER, MAP_ZOOM);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 18,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(mapObj);

    mapEdgeLayer = L.layerGroup().addTo(mapObj);
    mapNodeLayer = L.layerGroup().addTo(mapObj);

    // placement mode: one click drops the pending node here
    mapObj.on("click", function (e) {
        if (!placementPending) return;
        nodePositions[placementPending] = {
            lat: e.latlng.lat, lng: e.latlng.lng
        };
        savePositions();
        placementPending = null;
        nodePositionChanged(placementPending);   // refresh card + markers
    });

    mapRender();
}

function mapRender() {
    if (!mapObj) return;
    mapNodeLayer.clearLayers();
    mapEdgeLayer.clearLayers();
    mapEdges = [];
    mapHighlighted = null;

    var positioned = Object.keys(meshNodes).filter(function (id) {
        return nodePositions[id] != null;
    });

    document.getElementById("map-empty").classList
        .toggle("hidden", positioned.length > 0 || placementPending);

    // --- DIRECTIONAL edges: each node's own next-hops, separately ---
    positioned.forEach(function (id) {
        (routesByNode[id]?.r || []).forEach(function (rt) {
            var to = nodePositions[rt.n];
            if (!to || rt.n === id) return;
            if (rt.ri == null) return;   // no signal reading - no color
            mapEdges.push({
                a: id, b: rt.n, rssi: rt.ri, snr: rt.sn,
                hops: rt.h, cost: rt.c,
            });
        });
    });

    // draw each direction as its own slightly-offset curved line so
    // A->B and B->A are both visible
    mapEdges.forEach(function (e) {
        var from = nodePositions[e.a], to = nodePositions[e.b];
        var line = L.polyline(
            [[from.lat, from.lng], [to.lat, to.lng]],
            { color: linkColor(e.rssi), weight: 3, opacity: 0.85 }
        ).addTo(mapEdgeLayer);
        // curve: nudge midpoint perpendicular by ~10% of length, toward
        // each direction's own side, so paired directions separate
        curveEdge(line, e, from, to);

        line.addEventListener("mouseover", function (ev) {
            L.popup({ closeButton: false })
                .setLatLng(ev.latlng)
                .setContent(`<b>${e.a.slice(-4)} → ${e.b.slice(-4)}</b><br>` +
                    `RSSI ${e.rssi} dBm · SNR ${e.sn}<br>` +
                    `${isBlacklisted(e.a, e.b) ? "<b>BLACKLISTED</b>" : ""}`)
                .openOn(mapObj);
        });
        line.addEventListener("click", function () {
            highlightRoute(e.a);   // show this node's whole route set
        });
        e.line = line;
    });

    // --- markers ---
    positioned.forEach(function (id) {
        var p = nodePositions[id];
        var v = floodLevels[id]?.value;
        var color = v != null ? floodClass(v).color : "var(--primary)";
        var marker = L.circleMarker([p.lat, p.lng], {
            radius: 9,
            color: "#fff", weight: 2,
            fillColor: color, fillOpacity: 0.95,
        }).addTo(mapNodeLayer);
        marker.bindTooltip(id, { direction: "top" });

        if (id === placementPending) {
            marker.setStyle({ radius: 13, dashArray: "4 3" });
        }

        marker.on("click", function () {
            selectedNode = id;
            renderSideCard();
            graphRender();
            highlightRoute(id);
        });

        // drag to adjust (circleMarker doesn't drag; use a small
        // invisible draggable marker as the handle)
        var drag = L.marker([p.lat, p.lng], {
            icon: L.divIcon({ className: "drag-handle" }),
            draggable: true,
        }).addTo(mapNodeLayer);
        drag.on("dragend", function (ev) {
            var ll = ev.target.getLatLng();
            nodePositions[id] = { lat: ll.lat, lng: ll.lng };
            savePositions();
            nodePositionChanged(id);
        });
        // keep drag handle glued to the circle marker
        drag.on("drag", function (ev) {
            var ll = ev.target.getLatLng();
            marker.setLatLng(ll);
        });
    });

    // fit view to what's placed
    if (positioned.length) {
        var bounds = L.latLngBounds(positioned.map(function (id) {
            var p = nodePositions[id];
            return [p.lat, p.lng];
        }));
        mapObj.fitBounds(bounds.pad(0.25));
    }
}

// offset paired directional edges so both directions are visible
function curveEdge(line, e, from, to) {
    // A>B and B>A pair up: give each a fixed perpendicular offset.
    // Deterministic per pair: same edge pair always offsets the same
    // way, so refreshing doesn't reshuffle the visual.
    var key = [e.a, e.b].sort().join("~");
    var sign = (e.a < e.b) ? 1 : -1;
    var dx = to.lng - from.lng, dy = to.lat - from.lat;
    var len = Math.sqrt(dx * dx + dy * dy) || 1;
    var off = 0.00012 * sign;   // ~tens of meters at city zoom
    var mx = (from.lng + to.lng) / 2 - (dy / len) * off;
    var my = (from.lat + to.lat) / 2 + (dx / len) * off;
    line.setLatLngs([
        [from.lat, from.lng],
        [my, mx],
        [to.lat, to.lng],
    ]);
}

// node's full route view on the map: its next-hops bright, everything
// else dimmed; hovered/selected edge animated in ITS direction
function highlightRoute(nodeId) {
    var mine = {};
    mapEdges.forEach(function (e) {
        if (e.a === nodeId) mine[[e.a, e.b].join("~")] = e;
    });
    mapEdges.forEach(function (e) {
        var key = [e.a, e.b].join("~");
        if (key in mine) {
            e.line.setStyle({ weight: 5, opacity: 1 });
            // directed dash animation - flows A->B (this line's own
            // direction, the node's own view of its neighbor)
            animateFlow(e.line, mapObj, key);
        } else {
            e.line.setStyle({ weight: 2, opacity: 0.15 });
        }
    });
    mapHighlighted = { nodeId: nodeId };
}

// marching-dash CSS animation; class removed on next render.
// (Leaflet redraws SVG per zoom; the class lives on the SVG path)
function animateFlow(line, map, key) {
    var el = line._path;   // leaflet's internal SVG path
    if (!el) return;
    el.classList.add("flow-" + btoa(unescape(encodeURIComponent(key))).slice(0, 8));
    // simpler: one shared animation class - all highlighted edges flow
    el.classList.add("flow-anim");
}