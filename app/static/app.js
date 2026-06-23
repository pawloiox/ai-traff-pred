"use strict";

const REFRESH_MS = 30000;

const state = {
  map: null,
  ports: [],
  tiles: null,
  flowLayer: null,
  incidentsLayer: null,
  markers: {}, // point_id -> L.CircleMarker
  selectedPort: null,
};

const LEVEL_COLORS = {
  ok: "#2ea043",
  warning: "#d29922",
  critical: "#f85149",
  unknown: "#6e7681",
};

function fmtPct(r) {
  if (r === null || r === undefined) return "b.d.";
  return Math.round(r * 100) + "%";
}

function fmtTime(ts) {
  if (!ts) return "--";
  return new Date(ts * 1000).toLocaleTimeString("pl-PL");
}

async function getJSON(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`${url}: ${resp.status}`);
  return resp.json();
}

async function init() {
  const data = await getJSON("/api/ports");
  state.ports = data.ports;
  state.tiles = data.tiles;
  state.selectedPort = state.ports[0];

  initMap();
  initControls();
  initTabs();
  await refreshAll();
  setInterval(refreshAll, REFRESH_MS);
}

function initMap() {
  const c = state.selectedPort.center;

  // Ograniczenie obszaru mapy (maxBounds) do polskiego wybrzeza (od Szczecina do Trojmiasta)
  // zapobiega to ladowaniu kafelkow TomTom dla innych miast i oszczedza zapytania API
  const bounds = L.latLngBounds([53.20, 14.00], [54.90, 19.10]);

  state.map = L.map("map", {
    zoomControl: true,
    maxBounds: bounds.pad(0.05),
    maxBoundsViscosity: 1.0,
    minZoom: 8
  }).setView([c.lat, c.lon], 12);

  L.tileLayer(state.tiles.basemap, {
    maxZoom: 22,
    attribution: "&copy; TomTom",
  }).addTo(state.map);

  // Ograniczenie ladowania kafelkow flow/incidents tylko do okolic trzech portow:
  // Trojmiasto (Gdansk, Gdynia) i Szczecin-Swinoujscie
  // Dwa regiony sa polaczone w jeden bbox pokrywajacy polskie wybrzeze
  const tileBounds = L.latLngBounds([53.20, 14.00], [54.70, 19.10]);

  state.flowLayer = L.tileLayer(state.tiles.flow, { maxZoom: 22, opacity: 0.9, bounds: tileBounds });
  state.incidentsLayer = L.tileLayer(state.tiles.incidents, { maxZoom: 22, bounds: tileBounds });
  state.flowLayer.addTo(state.map);
  state.incidentsLayer.addTo(state.map);

  addLegend();
  createMarkers();
}

function addLegend() {
  const legend = L.control({ position: "bottomleft" });
  legend.onAdd = () => {
    const div = L.DomUtil.create("div", "legend");
    div.innerHTML =
      '<div class="legend-title">Punkty pomiarowe</div>' +
      legendRow("ok", "Plynnie") +
      legendRow("warning", "Zwolnienie") +
      legendRow("critical", "Zator / zamkniecie") +
      legendRow("unknown", "Brak danych") +
      '<div class="legend-sep"></div>' +
      '<div class="legend-title">Zdarzenia (TomTom)</div>' +
      legendArrow("warning", "Zwolnienie ruchu") +
      legendArrow("critical", "Zator / zamkniecie kierunku") +
      '<div class="legend-note">Strzalki to utrudnienia z danych TomTom. ' +
      "Wskazuja kierunek nitki, ktorej dotyczy zdarzenie; kolor oznacza jego nasilenie.</div>";
    return div;
  };
  legend.addTo(state.map);
}

function legendRow(level, label) {
  return `<div class="row"><span class="swatch" style="background:${LEVEL_COLORS[level]}"></span>${label}</div>`;
}

function legendArrow(level, label) {
  return `<div class="row"><span class="arrow" style="color:${LEVEL_COLORS[level]}">&#10148;</span>${label}</div>`;
}

function createMarkers() {
  state.ports.forEach((port) => {
    port.points.forEach((pt) => {
      const marker = L.circleMarker([pt.lat, pt.lon], {
        radius: 8,
        color: "#0b0f17",
        weight: 1.5,
        fillColor: LEVEL_COLORS.unknown,
        fillOpacity: 0.95,
        className: "point-marker",
      }).addTo(state.map);
      marker.bindPopup(`<strong>${pt.name}</strong><br/>${pt.road}<br/>Brak danych`);
      state.markers[pt.id] = marker;
    });
  });
}

function initControls() {
  const select = document.getElementById("portSelect");
  state.ports.forEach((p) => {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = p.name;
    select.appendChild(opt);
  });
  select.addEventListener("change", () => {
    const port = state.ports.find((p) => p.id === select.value);
    state.selectedPort = port;
    state.map.setView([port.center.lat, port.center.lon], 12);
    renderAll();
  });

  document.getElementById("flowToggle").addEventListener("change", (e) => {
    toggleLayer(state.flowLayer, e.target.checked);
  });
  document.getElementById("incidentsToggle").addEventListener("change", (e) => {
    toggleLayer(state.incidentsLayer, e.target.checked);
  });
  document.getElementById("refreshBtn").addEventListener("click", async () => {
    const btn = document.getElementById("refreshBtn");
    btn.disabled = true;
    btn.textContent = "Odswiezam...";
    try {
      await fetch("/api/refresh", { method: "POST" });
      await refreshAll();
    } finally {
      btn.disabled = false;
      btn.textContent = "Odswiez teraz";
    }
  });
}

function toggleLayer(layer, on) {
  if (on) layer.addTo(state.map);
  else state.map.removeLayer(layer);
}

function initTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      document.getElementById("panel-" + tab.dataset.tab).classList.add("active");
    });
  });
}

const cache = {};

async function refreshAll() {
  const [status, bottlenecks, reports, incidents, predictions] = await Promise.all([
    getJSON("/api/status"),
    getJSON("/api/bottlenecks?window=60&limit=15"),
    getJSON("/api/reports?limit=12"),
    getJSON("/api/incidents"),
    getJSON("/api/predictions"),
  ]);
  cache.status = status;
  cache.bottlenecks = bottlenecks.bottlenecks;
  cache.reports = reports.reports;
  cache.incidents = incidents.incidents;
  cache.predictions = predictions.predictions;

  document.getElementById("lastPoll").textContent =
    "Ostatni pomiar: " + fmtTime(status.last_poll);

  updateMarkers(status.points);
  renderAll();
}

function updateMarkers(points) {
  points.forEach((p) => {
    const marker = state.markers[p.point_id];
    if (!marker) return;
    const level = p.level || "unknown";
    marker.setStyle({ fillColor: LEVEL_COLORS[level] });
    marker.setRadius(level === "critical" ? 11 : 8);
    const path = marker.getElement && marker.getElement();
    if (path) {
      path.classList.toggle("marker-critical", level === "critical");
      path.classList.toggle("marker-warning", level === "warning");
    }
    const speed =
      p.current_speed != null
        ? `${Math.round(p.current_speed)} / ${Math.round(p.free_flow_speed)} km/h`
        : "b.d.";
    marker.setPopupContent(
      `<strong>${p.point_name}</strong><br/>${p.road || ""}<br/>` +
      `Kongestia: <b>${fmtPct(p.congestion_ratio)}</b> (${level})<br/>` +
      `Predkosc: ${speed}` +
      (p.road_closure ? "<br/><b>DROGA ZAMKNIETA</b>" : "")
    );
  });
}

function filterPort(rows) {
  if (!state.selectedPort) return rows;
  return rows.filter((r) => r.port_id === state.selectedPort.id);
}

function renderAll() {
  renderStatus();
  renderBottlenecks();
  renderReports();
  renderIncidents();
  renderPredictions();
}

function ratioBar(level, ratio) {
  const pct = ratio != null ? Math.round(ratio * 100) : 0;
  return `<div class="ratio-bar"><div class="ratio-fill ${level}" style="width:${pct}%"></div></div>`;
}

function emptyMsg(text) {
  return `<div class="empty">${text}</div>`;
}

function renderStatus() {
  const points = filterPort(cache.status?.points || []);
  const el = document.getElementById("panel-status");
  if (!points.length) {
    el.innerHTML = emptyMsg("Oczekiwanie na dane pomiarowe...");
    return;
  }
  el.innerHTML = points
    .map((p) => {
      const level = p.level || "unknown";
      return `<div class="card level-${level}">
        <h3>${p.point_name}<span class="badge ${level}">${fmtPct(p.congestion_ratio)}</span></h3>
        <div class="meta">${p.road || ""}</div>
        <div class="body">
          Predkosc: ${p.current_speed != null ? Math.round(p.current_speed) : "b.d."} km/h
          (swobodna ${p.free_flow_speed != null ? Math.round(p.free_flow_speed) : "b.d."} km/h)
          ${p.road_closure ? "<br/><b>Droga zamknieta</b>" : ""}
        </div>
        ${ratioBar(level, p.congestion_ratio)}
      </div>`;
    })
    .join("");
}

function renderBottlenecks() {
  const rows = filterPort(cache.bottlenecks || []);
  const el = document.getElementById("panel-bottlenecks");
  if (!rows.length) {
    el.innerHTML = emptyMsg("Brak waskich gardel w ostatniej godzinie.");
    return;
  }
  el.innerHTML = rows
    .map((b, i) => {
      const level = b.level || "unknown";
      return `<div class="card level-${level}">
        <h3>#${i + 1} ${b.point_name}<span class="badge ${level}">${fmtPct(b.avg_ratio)}</span></h3>
        <div class="meta">${b.road || ""} &middot; ${b.samples} probek</div>
        <div class="body">Srednia: ${fmtPct(b.avg_ratio)} &middot; Maks: ${fmtPct(b.max_ratio)}</div>
        ${ratioBar(level, b.avg_ratio)}
      </div>`;
    })
    .join("");
}

function renderReports() {
  const rows = filterPort(cache.reports || []);
  const el = document.getElementById("panel-reports");
  if (!rows.length) {
    el.innerHTML = emptyMsg("Brak raportow operacyjnych - ruch w normie.");
    return;
  }
  el.innerHTML = rows
    .map((r) => {
      const level = r.level || "unknown";
      const badges =
        (r.rising ? '<span class="badge rising">narasta</span>' : "") +
        (r.is_anomaly ? '<span class="badge anomaly">anomalia</span>' : "");
      return `<div class="card level-${level}">
        <h3>${r.headline}${badges}</h3>
        <div class="meta">${r.road || ""}</div>
        <div class="body">
          <b>Przyczyna:</b> ${r.cause}<br/>
          <b>Rekomendacja:</b> ${r.recommendation}
          ${r.prediction ? `<br/><b>Prognoza (${r.prediction.horizon_minutes} min):</b> ${fmtPct(r.prediction.predicted_ratio)}` : ""}
        </div>
      </div>`;
    })
    .join("");
}

function renderIncidents() {
  const rows = filterPort(cache.incidents || []);
  const el = document.getElementById("panel-incidents");
  if (!rows.length) {
    el.innerHTML = emptyMsg("Brak zgloszonych incydentow.");
    return;
  }
  el.innerHTML = rows
    .map((inc) => {
      const delay = inc.delay_seconds ? `${Math.round(inc.delay_seconds / 60)} min opoznienia` : "";
      return `<div class="card level-warning">
        <h3>${inc.category_label || "Incydent"}</h3>
        <div class="meta">${inc.from_name || ""} ${inc.to_name ? "&rarr; " + inc.to_name : ""}</div>
        <div class="body">${inc.description || ""} ${delay ? "<br/>" + delay : ""}</div>
      </div>`;
    })
    .join("");
}

function renderPredictions() {
  const rows = filterPort(cache.predictions || []);
  const el = document.getElementById("panel-predictions");
  if (!rows.length) {
    el.innerHTML = emptyMsg("Za malo danych do prognozy (poczekaj kilka cykli).");
    return;
  }
  el.innerHTML = rows
    .map((p) => {
      const level = p.rising ? "critical" : "ok";
      const arrow = p.rising ? "&#9650; narasta" : "&#9660; stabilnie/maleje";
      return `<div class="card level-${level}">
        <h3>${p.point_name}${p.rising ? '<span class="badge rising">narasta</span>' : ""}</h3>
        <div class="meta">${p.road || ""} &middot; ${p.samples} probek</div>
        <div class="body">
          Teraz: ${fmtPct(p.current_ratio)} &rarr; za ${p.horizon_minutes} min: <b>${fmtPct(p.predicted_ratio)}</b><br/>
          Trend: ${arrow} (${p.slope_per_10min > 0 ? "+" : ""}${(p.slope_per_10min * 100).toFixed(1)} pkt%/10 min)
        </div>
      </div>`;
    })
    .join("");
}

init().catch((err) => {
  document.getElementById("panel-status").innerHTML = emptyMsg("Blad inicjalizacji: " + err.message);
  console.error(err);
});
