// The SSE connection: how live updates arrive.
//
// This file is ALSO the page's event router: one place decides
// what each channel type does to the shared state.

function connectStream() {
    const es = new EventSource(API_BASE + "/stream");

    es.onopen = async () => {
        // Fires on the first connect AND after every auto-reconnect.
        streamUp = true;
        await loadAll().catch(() => { });
        renderAll();
    };

    es.onerror = () => { streamUp = false; renderStats(); };
    // (EventSource retries by itself - nothing to do here.)

    es.onmessage = (e) => {
        try { handleEvent(JSON.parse(e.data)); }
        catch (err) { console.error("bad event", e.data, err); }
    };
}

function handleEvent(msg) {
    const { channel, village, node_id, data, ts } = msg;

    // client-side diagnostics: what this browser is receiving
    diag.events += 1;
    diag.lastEvent = new Date();

    switch (channel) {

        // telemetry: data fields ARE node fields, merge directly 
        case "water":
        case "battery":
        case "gps":
        case "signal": {
            const node = nodes[nodeKey(village, node_id)];
            if (!node) { loadVillage(village); break; }
            Object.assign(node, data);
            node.last_seen = ts;
            updateMarker(village, node_id);
            if (selectedKey === nodeKey(village, node_id)) renderNodePanel();
            break;
        }

        // alert: into the feed + flash the node on the map 
        case "alert": {
            addAlert({
                village_id: village, node_id, type: data.type,
                value: data.value, timestamp: ts
            });
            flashNode(village, node_id);
            break;
        }

        // node online/offline, or an announce (deployment / re-mesh) 
        case "node_status": {
            const node = nodes[nodeKey(village, node_id)];
            if (data.event === "announce") {
                // announce carries parent/depth + the freshly rebuilt topology
                if (node) {
                    node.parent_id = data.parent;
                    node.depth = data.depth;
                    if (node.coordinates == null && data.lat != null)
                        node.coordinates = { lat: data.lat, lng: data.lng };
                    node.status = "online";
                }
                if (villages[village]) villages[village].topology = data.topology;
                if (!node) { loadVillage(village); break; }
                renderLines();
            } else {
                if (node) node.status = data.online ? "online" : "offline";
                else { loadVillage(village); break; }
            }
            updateMarker(village, node_id);
            if (selectedKey === nodeKey(village, node_id)) renderNodePanel();
            renderVillageList();
            break;
        }

        // master online/offline: the whole village's liveness 
        case "village_status": {
            if (!villages[village]) { loadAll().then(renderAll); break; }
            villages[village].is_online = data.online;
            renderVillageList();
            refreshStats();
            break;
        }

        // authoritative mesh tree from the master 
        case "topology": {
            if (villages[village]) villages[village].topology = data.topology;
            renderLines();
            break;
        }
    }
}

// Update the browser-side diagnostics once per second: events/s and
// how long since the last event arrived (staleness indicator).
setInterval(() => {
    if (diag.lastEvent) {
        const now = new Date();
        diag.eventRate = diag.eventRate * 0.7 + 0;   // placeholder decay
    }
}, 1000);