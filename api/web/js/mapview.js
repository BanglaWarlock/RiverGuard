let mapObj;
function mapInit() {
    mapObj = L.map("map").setView([1.4, 110.9], 8);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 18,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(mapObj);
    mapRender();
}
function mapRender() {
    // nothing to place yet: mesh nodes have no coordinates until GPS
    // data or manual placement exists. Show the empty note.
    const positioned = Object.values(meshNodes).filter(n => n.lat != null);
    document.getElementById("map-empty").classList.toggle("hidden", positioned.length > 0);
}