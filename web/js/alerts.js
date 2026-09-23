// The live alert feed in the sidebar.

function addAlert(a) {
    alerts.unshift(a);
    alerts = alerts.slice(0, MAX_ALERT_ROWS);
    prependAlertRow(a, /* isNew= */ true);
}

function alertText(a) {
    if (a.type === "flood") return `water at ${a.value} ft`;
    if (a.type === "battery") return `battery ${a.value} V`;
    if (a.type === "gps_moved") return `moved ${a.value ?? "?"} m`;
    return "";
}

function prependAlertRow(a, isNew) {
    const feed = document.getElementById("alert-feed");
    const meta = ALERT_META[a.type] || { icon: "⚠️", label: a.type, color: "#666" };

    const row = document.createElement("div");
    row.className = "alert-entry" + (isNew ? " new" : "");
    row.innerHTML =
        `<span class="badge" style="background:${meta.color}">${meta.icon} ${meta.label}</span>` +
        `<span class="who">${a.node_id}</span>` +
        `<span class="what">${alertText(a)} · ${a.village_id}</span>` +
        `<time>${fmtTime(a.timestamp)}</time>`;

    const empty = feed.querySelector(".empty");
    if (empty) empty.remove();
    feed.prepend(row);
    while (feed.children.length > MAX_ALERT_ROWS) feed.lastChild.remove();
}

function renderAlertFeed() {
    const feed = document.getElementById("alert-feed");
    feed.innerHTML = "";
    if (!alerts.length) {
        feed.innerHTML = `<div class="empty">no alerts yet</div>`;
        return;
    }
    // oldest at the bottom, newest at the top
    [...alerts].reverse().forEach((a) => prependAlertRow(a, false));
}