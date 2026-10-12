// The link-policy panel: current blacklist + version history.
// Current state comes from activeBlacklist (kept fresh by stream
// events); history is fetched once and on policy change.

var blacklistHistory = [];

async function renderBlacklistPanel() {
    const cur = document.getElementById("blacklist-current");
    const hist = document.getElementById("blacklist-history");

    // --- current policy ---
    if (!activeBlacklist) {
        cur.innerHTML = `<p class="none">No policy published.</p>`;
    } else {
        const edges = activeBlacklist.edges || [];
        const reason = activeBlacklist.reason ? ` · ${activeBlacklist.reason}` : "";
        const edgeRows = edges.length
            ? edges.map(e => `<div class="bl-edge">${e[0]} ⇄ ${e[1]}</div>`).join("")
            : `<p class="none">No links disabled.</p>`;
        cur.innerHTML =
            `<div class="bl-current">` +
            `<span class="flood-class" style="background:${edges.length ? "var(--level3)" : "var(--level0)"}">` +
            `${edges.length} disabled</span>` +
            `<span class="bl-meta">v${activeBlacklist.v} · seq ${activeBlacklist.sequence}${reason}</span>` +
            `</div>${edgeRows}`;
    }

    // --- history (fetch if we haven't) ---
    if (!blacklistHistory.length) {
        blacklistHistory = await api("/mesh/blacklists?limit=10").catch(() => []);
    }
    const active = activeBlacklist?.sequence;
    hist.innerHTML = blacklistHistory.length
        ? blacklistHistory.map(b => {
            const isCurrent = b.sequence === active;
            const edges = (b.edges || []).map(e => `${e[0]}⇄${e[1]}`).join(", ") || "none";
            return `<div class="bl-row${isCurrent ? " current" : ""}">` +
                `<span class="bl-meta">v${b.v} · seq ${b.sequence}${isCurrent ? " · active" : ""}</span>` +
                `<span class="bl-edges">${edges}</span></div>`;
        }).join("")
        : `<p class="none">No history.</p>`;
}