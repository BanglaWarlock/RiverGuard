// Boot sequence and page wiring - the only orchestrator.

function switchTab(name) {
    document.querySelectorAll(".tab").forEach(t =>
        t.classList.toggle("active", t.dataset.tab === name));
    document.querySelectorAll(".tab-panel").forEach(p =>
        p.classList.toggle("active", p.id === `tab-${name}`));
    if (name === "map" && typeof mapObj !== "undefined" && mapObj)
        setTimeout(() => mapObj.invalidateSize(), 50);
    if (name === "network") graphRender();
}

async function boot() {
    // theme
    document.documentElement.dataset.theme = localStorage.getItem("rg_theme") || "light";
    document.getElementById("theme-btn").onclick = () => {
        const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
        document.documentElement.dataset.theme = next;
        localStorage.setItem("rg_theme", next);
        graphRender();
    };

    // tabs
    document.querySelectorAll(".tab").forEach(t =>
        t.onclick = () => switchTab(t.dataset.tab));
    document.querySelectorAll(".side-tab").forEach(t =>
        t.onclick = () => {
            sideTab = t.dataset.side;
            document.querySelectorAll(".side-tab").forEach(s =>
                s.classList.toggle("active", s === t));
            renderSideCard();
        });

    document.getElementById("refresh-btn").onclick = async () => {
        await loadAll().catch(() => { });
        refreshStats();
        graphRender(); renderSideCard(); renderFloodList();
    };

    graphInit(); mapInit();
    await loadAll().catch(e => console.error("initial load failed", e));
    refreshStats();
    graphRender(); renderSideCard(); renderFloodList(); renderBlacklistPanel();
    connectStream();

    // keep the header summary fresh
    setInterval(refreshStats, 30000);
}

// One-line executive summary of the network, from /stats.
async function refreshStats() {
    const s = await api("/stats").catch(() => null);
    if (!s) return;
    document.getElementById("stats-line").innerHTML =
        `${s.nodes_recent}/${s.node_count} active · ` +
        `avg ${s.avg_rssi ?? "?"} dBm · max SF ${s.max_sf ?? "?"} · ` +
        `${s.blacklist_active_edges} blocked · ` +
        `<span class="dot ${streamUp ? "live" : ""}"></span>`;
}

boot();