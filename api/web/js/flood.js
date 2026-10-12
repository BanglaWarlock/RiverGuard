function renderFloodList() {
    const el = document.getElementById("flood-list");
    const ids = Object.keys(meshNodes);
    if (!ids.length) { el.innerHTML = `<p class="none">No nodes yet.</p>`; return; }

    el.innerHTML = "";
    ids.forEach(id => {
        const f = floodLevels[id];
        const v = f?.value ?? 0.5;   // default mid
        const cls = floodClass(f?.value ?? 0.5);
        const row = document.createElement("div");
        row.className = "flood-row";
        row.innerHTML = `
      <div class="row-head">
        <span><b>${id}</b></span>
        <span class="flood-class" style="background:${cls.color}">${cls.label}</span>
      </div>
      <input type="range" min="0" max="1" step="0.01" value="${v}">`;
        row.querySelector("input").addEventListener("input", (e) => {
            const val = parseFloat(e.target.value);
            floodLevels[id] = { value: val, source: "local" };
            saveFlood();
            const c = floodClass(val);
            row.querySelector(".flood-class").textContent = c.label;
            row.querySelector(".flood-class").style.background = c.color;
            if (selectedNode === id) renderSideCard();
            graphRender();   // node color could reflect level later
        });
        el.appendChild(row);
    });
}