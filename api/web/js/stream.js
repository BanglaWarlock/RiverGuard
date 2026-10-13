// The SSE connection: how live updates arrive.
//
// This file is ALSO the page's event router: one place decides
// what each channel type does to the shared state.

function connectStream() {
    const es = new EventSource(API_BASE + "/stream");
    es.onopen = async () => {
        streamUp = true; refreshStats();
        await loadAll().catch(() => { });
        graphRender(); renderSideCard(); renderFloodList();
    };
    es.onerror = () => { streamUp = false; refreshStats(); };
    es.onmessage = (e) => {
        try {
            const msg = JSON.parse(e.data);
            handleMeshEvent(msg);
            renderStreamLine(msg);
        } catch (err) { console.error("bad event", e.data, err); }
    };
}

function handleMeshEvent(msg) {
    const ev = msg.data?.event;
    const id = msg.node_id;

    if (ev === "telemetry" && id) {
        // full payload arrives in the event - merge straight on
        meshNodes[id] = meshNodes[id] || { node_id: id };
        Object.assign(meshNodes[id], msg.data.payload, { last_seen: msg.ts });
        if (selectedNode === id) renderSideCard();
        graphRender();
        const g = gNodes.querySelector(`g.node[data-id="${id}"]`);
        if (g) {
            g.classList.add("pulse");
            setTimeout(() => g.classList.remove("pulse"), 1200);
        }
    } else if (ev === "route" && id) {
        // summary only - refetch that node's newest report
        api(`/mesh/routes?node_id=${id}&limit=1`).then(rs => {
            if (rs[0]) { routesByNode[id] = rs[0].payload; graphRender(); }
        }).catch(() => { });
    } else if (ev === "blacklist") {
        activeBlacklist = msg.data.payload;   // full payload, edges included
        blacklistHistory = [];                // history changed - refetch on next render
        graphRender();                        // dashed edges update
        renderBlacklistPanel();
    }
}