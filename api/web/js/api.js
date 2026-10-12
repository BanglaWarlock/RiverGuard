async function api(path) {
    const res = await fetch(API_BASE + path);
    if (!res.ok) throw new Error(`${path} -> ${res.status}`);
    return res.json();
}

async function loadAll() {
    const [nodes, routes, currentBl] = await Promise.all([
        api("/mesh/nodes").catch(() => []),
        api("/mesh/routes?limit=200").catch(() => []),
        api("/mesh/blacklists/current").catch(() => null),
    ]);
    meshNodes = {};
    nodes.forEach(n => { meshNodes[n.node_id] = n; });

    // newest route report per node (API returns newest-first)
    routesByNode = {};
    routes.forEach(r => {
        const id = r.node_id;
        if (!routesByNode[id]) routesByNode[id] = r.payload;
    });

    activeBlacklist = currentBl;   // already the flat shape: {v, sequence, edges, ...}
    loadFlood();
}