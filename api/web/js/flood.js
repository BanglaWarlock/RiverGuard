// The Islands tab: per-node local configuration, grouped by island.
// Each card: flood level (slider + class), position (lat/lng inputs
// + place-on-map button). All values are LOCAL ONLY (localStorage);
// the mesh reports network data, never water or GPS.

function renderFloodList() {
  var el = document.getElementById("flood-list");
  var groups = islands();
  if (!groups.length) { el.innerHTML = `<p class="none">No nodes yet.</p>`; return; }

  el.innerHTML = "";
  groups.forEach(function (group) {
    var head = document.createElement("h3");
    head.className = "island-head";
    head.textContent = `Island of ${group.members[0].slice(-4)} — ${group.members.length} node(s)`;
    el.appendChild(head);

    group.members.forEach(function (id) {
      el.appendChild(nodeCard(id));
    });
  });
}

function nodeCard(id) {
  var f = floodLevels[id] || {};
  var v = f.value != null ? f.value : 0.5;
  var cls = floodClass(v);
  var p = nodePositions[id];

  var card = document.createElement("div");
  card.className = "flood-row node-card";
  card.dataset.node = id;
  card.innerHTML = `
      <div class="row-head">
        <span><b>${id}</b>${selectedNode === id ? ` <span class="mini-tag">selected</span>` : ""}</span>
        <span class="flood-class" style="background:${cls.color}">${cls.label}</span>
      </div>
      <div class="row-ctl">
        <input type="range" min="0" max="1" step="0.01" value="${v}">
        <span class="lvl-pct">${Math.round(v * 100)}%</span>
      </div>
      <div class="pos-row">
        <input type="number" step="any" class="pos-lat" placeholder="lat" value="${p?.lat ?? ""}">
        <input type="number" step="any" class="pos-lng" placeholder="lng" value="${p?.lng ?? ""}">
        <button type="button" class="place-btn">${p ? "Move on map" : "Place on map"}</button>
      </div>`;

  // slider: live class + pct label
  var range = card.querySelector("input[type=range]");
  range.addEventListener("input", function () {
    var val = parseFloat(range.value);
    floodLevels[id] = { value: val };
    saveFlood();
    var c = floodClass(val);
    card.querySelector(".flood-class").textContent = c.label;
    card.querySelector(".flood-class").style.background = c.color;
    card.querySelector(".lvl-pct").textContent = Math.round(val * 100) + "%";
    mapRender();   // marker color follows the level
  });

  // manual lat/lng entry (option C)
  card.querySelector(".pos-lat").addEventListener("change", function () {
    setPos(id, this.value, card.querySelector(".pos-lng").value);
  });
  card.querySelector(".pos-lng").addEventListener("change", function () {
    setPos(id, card.querySelector(".pos-lat").value, this.value);
  });

  // place on map (option A): switch to map tab, arm placement
  card.querySelector(".place-btn").addEventListener("click", function () {
    placementPending = id;
    switchTab("map");
  });

  return card;
}

function setPos(id, latS, lngS) {
  var lat = parseFloat(latS), lng = parseFloat(lngS);
  if (isFinite(lat) && isFinite(lng)) {
    nodePositions[id] = { lat: lat, lng: lng };
    savePositions();
    mapRender();
  }
  renderFloodList();   // refresh the card display (or clear inputs)
}

// called by mapview after a placement click or marker drag
function nodePositionChanged(id) {
  renderFloodList();
  mapRender();
}