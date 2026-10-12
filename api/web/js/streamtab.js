function renderStreamLine(msg) {
    const feed = document.getElementById("stream-feed");
    const row = document.createElement("div");
    row.className = "stream-line";
    row.innerHTML =
        `<span class="chan">${msg.data?.event || "?"}</span> ` +
        `${msg.node_id || ""} ${JSON.stringify(msg.data).slice(0, 120)}`;
    feed.prepend(row);
    while (feed.children.length > 200) feed.lastChild.remove();
}