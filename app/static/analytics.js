"use strict";

/**
 * analytics.js — Panel analityki firmowej (Osoba 3)
 *
 * Wykresy Chart.js: historia kongestii, dzienny wzorzec, scoring ryzyka, pogoda.
 * Ladowany po app.js, korzysta z globalnych state i getJSON z app.js.
 */

const analyticsState = {
  historyChart: null,
  patternChart: null,
  selectedPointId: null,
  riskData: [],
  weatherData: [],
};

const RISK_COLORS = {
  low: "#3fb950",
  medium: "#d29922",
  high: "#f85149",
  very_high: "#da3633",
};

const RISK_ICONS = {
  low: "✅",
  medium: "⚠️",
  high: "🔴",
  very_high: "🚨",
};

const WEATHER_ICONS = {
  0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️",
  45: "🌫️", 48: "🌫️",
  51: "🌦️", 53: "🌧️", 55: "🌧️",
  56: "🧊", 57: "🧊",
  61: "🌧️", 63: "🌧️", 65: "🌧️",
  66: "🧊", 67: "🧊",
  71: "🌨️", 73: "🌨️", 75: "❄️",
  77: "❄️",
  80: "🌦️", 81: "🌧️", 82: "⛈️",
  85: "🌨️", 86: "❄️",
  95: "⛈️", 96: "⛈️", 99: "⛈️",
};

function getWeatherIcon(code) {
  if (code === null || code === undefined) return "❓";
  return WEATHER_ICONS[code] || "🌡️";
}

function getWeatherLabel(code) {
  if (code === null || code === undefined) return "Brak danych";
  const labels = {
    0: "Bezchmurnie", 1: "Prawie bezchmurnie", 2: "Częściowe zachmurzenie", 3: "Zachmurzenie całkowite",
    45: "Mgła", 48: "Mgła z szadzią",
    51: "Mżawka lekka", 53: "Mżawka umiarkowana", 55: "Mżawka gęsta",
    61: "Deszcz lekki", 63: "Deszcz umiarkowany", 65: "Deszcz silny",
    71: "Śnieg lekki", 73: "Śnieg umiarkowany", 75: "Śnieg silny",
    80: "Przelotny deszcz", 81: "Deszcz przelotny um.", 82: "Ulewa",
    95: "Burza", 96: "Burza z gradem", 99: "Silna burza z gradem",
  };
  return labels[code] || `Kod pogody: ${code}`;
}

// --- Rendering ---

async function loadAnalyticsData() {
  const results = await Promise.allSettled([
    getJSON("/api/risk-scores"),
    getJSON("/api/weather"),
  ]);
  const val = (i, fb) => results[i].status === "fulfilled" ? results[i].value : fb;
  analyticsState.riskData = val(0, { risk_scores: [] }).risk_scores;
  analyticsState.weatherData = val(1, { weather: [] }).weather;

  // Automatyczny wybor pierwszego punktu jesli nie wybrano
  if (!analyticsState.selectedPointId && analyticsState.riskData.length > 0) {
    analyticsState.selectedPointId = analyticsState.riskData[0].point_id;
  }
}

function renderAnalyticsPanel() {
  const el = document.getElementById("panel-analytics");
  if (!el) return;

  el.innerHTML = `
    <div class="analytics-header">
      <h2 class="analytics-title">📊 Analityka Firmowa</h2>
      <div class="analytics-controls">
        <label for="analyticsPointSelect">Punkt:</label>
        <select id="analyticsPointSelect"></select>
      </div>
    </div>

    <div class="analytics-grid">
      <div class="analytics-section">
        <h3 class="section-title">🎯 Scoring Ryzyka Opóźnień</h3>
        <div id="riskScoresContainer"></div>
      </div>

      <div class="analytics-section">
        <h3 class="section-title">🌤️ Pogoda w Portach</h3>
        <div id="weatherContainer"></div>
      </div>

      <div class="analytics-section analytics-chart-section">
        <h3 class="section-title">📈 Historia Kongestii (7 dni)</h3>
        <div class="chart-wrapper">
          <canvas id="historyChartCanvas"></canvas>
        </div>
      </div>

      <div class="analytics-section analytics-chart-section">
        <h3 class="section-title">📅 Profil Tygodniowy</h3>
        <div class="chart-wrapper">
          <canvas id="patternChartCanvas"></canvas>
        </div>
      </div>
    </div>
  `;

  // Populate point selector
  const select = document.getElementById("analyticsPointSelect");
  if (select && analyticsState.riskData.length > 0) {
    analyticsState.riskData.forEach((r) => {
      const opt = document.createElement("option");
      opt.value = r.point_id;
      opt.textContent = `${r.point_name} (${r.road || ""})`;
      if (r.point_id === analyticsState.selectedPointId) opt.selected = true;
      select.appendChild(opt);
    });
    select.addEventListener("change", () => {
      analyticsState.selectedPointId = select.value;
      renderRiskScores();
      loadCharts();
    });
  }

  renderRiskScores();
  renderWeather();
  loadCharts();
}

function renderRiskScores() {
  const container = document.getElementById("riskScoresContainer");
  if (!container) return;

  // Filtruj do wybranego portu jesli state.selectedPort jest dostepny
  let scores = analyticsState.riskData;
  if (typeof state !== "undefined" && state.selectedPort) {
    scores = scores.filter((r) => r.port_id === state.selectedPort.id);
  }

  if (!scores.length) {
    container.innerHTML = '<div class="empty">Brak danych scoringu.</div>';
    return;
  }

  container.innerHTML = scores
    .map((r) => {
      const risk = r.risk || {};
      const level = risk.level || "low";
      const color = RISK_COLORS[level] || RISK_COLORS.low;
      const icon = RISK_ICONS[level] || "✅";
      const c = r.components || {};

      return `<div class="risk-card" style="--risk-color: ${color}">
        <div class="risk-header">
          <span class="risk-icon">${icon}</span>
          <div class="risk-info">
            <div class="risk-name">${r.point_name || r.point_id}</div>
            <div class="risk-road">${r.road || ""}</div>
          </div>
          <div class="risk-score-badge" style="background: ${color}20; color: ${color}; border: 1px solid ${color}40">
            ${r.score}
          </div>
        </div>
        <div class="risk-label" style="color: ${color}">${risk.label || ""}</div>
        <div class="risk-components">
          <div class="risk-comp">
            <span class="comp-label">Ruch</span>
            <div class="comp-bar"><div class="comp-fill" style="width: ${(c.traffic_ratio_live || 0) * 100}%; background: ${color}"></div></div>
            <span class="comp-val">${Math.round((c.traffic_ratio_live || 0) * 100)}%</span>
          </div>
          <div class="risk-comp">
            <span class="comp-label">Anomalia</span>
            <div class="comp-bar"><div class="comp-fill" style="width: ${(c.historical_anomaly || 0) * 100}%; background: ${color}"></div></div>
            <span class="comp-val">${Math.round((c.historical_anomaly || 0) * 100)}%</span>
          </div>
          <div class="risk-comp">
            <span class="comp-label">Pogoda</span>
            <div class="comp-bar"><div class="comp-fill" style="width: ${(c.weather_penalty || 0) * 100}%; background: ${color}"></div></div>
            <span class="comp-val">${Math.round((c.weather_penalty || 0) * 100)}%</span>
          </div>
          <div class="risk-comp">
            <span class="comp-label">Port</span>
            <div class="comp-bar"><div class="comp-fill" style="width: ${(c.port_ship_penalty || 0) * 100}%; background: ${color}"></div></div>
            <span class="comp-val">${Math.round((c.port_ship_penalty || 0) * 100)}%</span>
          </div>
          <div class="risk-comp">
            <span class="comp-label">Pora dnia</span>
            <div class="comp-bar"><div class="comp-fill" style="width: ${(c.temporal_peak_penalty || 0) * 100}%; background: ${color}"></div></div>
            <span class="comp-val">${Math.round((c.temporal_peak_penalty || 0) * 100)}%</span>
          </div>
        </div>
        ${r.temporal ? `<div class="risk-temporal">
          ${r.temporal.is_rush_hour ? '<span class="temp-badge rush">🕐 Godzina szczytu</span>' : ""}
          ${r.temporal.is_weekend ? '<span class="temp-badge weekend">📅 Weekend</span>' : ""}
          ${r.temporal.is_holiday ? '<span class="temp-badge holiday">🎉 Święto</span>' : ""}
        </div>` : ""}
      </div>`;
    })
    .join("");
}

function renderWeather() {
  const container = document.getElementById("weatherContainer");
  if (!container) return;

  const weather = analyticsState.weatherData;
  if (!weather.length) {
    container.innerHTML = '<div class="empty">Oczekiwanie na dane pogodowe...</div>';
    return;
  }

  // Mapowanie port_id -> nazwa
  const portNames = {};
  if (typeof state !== "undefined" && state.ports) {
    state.ports.forEach((p) => { portNames[p.id] = p.name; });
  }

  container.innerHTML = weather
    .map((w) => {
      const icon = getWeatherIcon(w.weather_code);
      const label = getWeatherLabel(w.weather_code);
      const penalty = w.weather_penalty || 0;
      const penaltyColor = penalty > 0.5 ? RISK_COLORS.high : penalty > 0.2 ? RISK_COLORS.medium : RISK_COLORS.low;
      const portName = portNames[w.port_id] || w.port_id;

      return `<div class="weather-card">
        <div class="weather-header">
          <span class="weather-icon-big">${icon}</span>
          <div>
            <div class="weather-port">${portName}</div>
            <div class="weather-label">${label}</div>
          </div>
        </div>
        <div class="weather-details">
          <div class="weather-stat">
            <span class="stat-icon">🌡️</span>
            <span>${w.temperature != null ? w.temperature.toFixed(1) + "°C" : "b.d."}</span>
          </div>
          <div class="weather-stat">
            <span class="stat-icon">🌧️</span>
            <span>${w.rain != null ? w.rain.toFixed(1) + " mm" : "0 mm"}</span>
          </div>
          <div class="weather-stat">
            <span class="stat-icon">💨</span>
            <span>${w.wind_speed != null ? Math.round(w.wind_speed) + " km/h" : "b.d."}</span>
          </div>
          <div class="weather-stat">
            <span class="stat-icon">👁️</span>
            <span>${w.visibility != null ? (w.visibility >= 1000 ? (w.visibility / 1000).toFixed(1) + " km" : Math.round(w.visibility) + " m") : "b.d."}</span>
          </div>
        </div>
        <div class="weather-penalty" style="color: ${penaltyColor}">
          Wpływ na ruch: ${Math.round(penalty * 100)}%
          <div class="ratio-bar" style="margin-top: 4px">
            <div class="ratio-fill" style="width: ${penalty * 100}%; background: ${penaltyColor}"></div>
          </div>
        </div>
      </div>`;
    })
    .join("");
}

async function loadCharts() {
  const pointId = analyticsState.selectedPointId;
  if (!pointId) return;

  // Chart colors based on theme
  const isLight = document.documentElement.getAttribute("data-theme") === "light";
  const gridColor = isLight ? "rgba(0,0,0,0.08)" : "rgba(255,255,255,0.08)";
  const textColor = isLight ? "#5a6270" : "#8b949e";

  Chart.defaults.color = textColor;
  Chart.defaults.borderColor = gridColor;

  // --- History chart ---
  try {
    const histData = await getJSON(`/api/analytics/congestion-history?point_id=${pointId}&days=7`);
    const history = (histData.history || []).filter((h) => h.point_id === pointId);

    if (analyticsState.historyChart) {
      analyticsState.historyChart.destroy();
      analyticsState.historyChart = null;
    }

    const histCanvas = document.getElementById("historyChartCanvas");
    if (histCanvas && history.length > 0) {
      const labels = history.map((h) => {
        const d = new Date(h.hour_ts * 1000);
        return d.toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit" }) + " " +
               d.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" });
      });

      analyticsState.historyChart = new Chart(histCanvas, {
        type: "line",
        data: {
          labels: labels,
          datasets: [
            {
              label: "Średnia kongestia",
              data: history.map((h) => Math.round((h.avg_ratio || 0) * 100)),
              borderColor: "#58a6ff",
              backgroundColor: "rgba(88, 166, 255, 0.1)",
              fill: true,
              tension: 0.3,
              pointRadius: 0,
              pointHoverRadius: 4,
              borderWidth: 2,
            },
            {
              label: "Maksimum",
              data: history.map((h) => Math.round((h.max_ratio || 0) * 100)),
              borderColor: "#f8514980",
              backgroundColor: "transparent",
              borderDash: [5, 5],
              tension: 0.3,
              pointRadius: 0,
              pointHoverRadius: 4,
              borderWidth: 1.5,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { intersect: false, mode: "index" },
          plugins: {
            legend: { position: "top", labels: { boxWidth: 12, padding: 10, font: { size: 11 } } },
            tooltip: {
              backgroundColor: isLight ? "rgba(255,255,255,0.95)" : "rgba(18,23,32,0.95)",
              titleColor: isLight ? "#1a1d23" : "#e6edf3",
              bodyColor: isLight ? "#5a6270" : "#8b949e",
              borderColor: isLight ? "rgba(0,0,0,0.1)" : "rgba(255,255,255,0.1)",
              borderWidth: 1,
              padding: 10,
              displayColors: true,
              callbacks: { label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y}%` },
            },
          },
          scales: {
            x: {
              grid: { display: false },
              ticks: { maxTicksLimit: 12, maxRotation: 45, font: { size: 10 } },
            },
            y: {
              beginAtZero: true,
              max: 100,
              ticks: { callback: (v) => v + "%", font: { size: 10 } },
              grid: { color: gridColor },
            },
          },
        },
      });
    }
  } catch (e) {
    console.warn("Analytics history chart error:", e);
  }

  // --- Daily pattern chart ---
  try {
    const patData = await getJSON(`/api/analytics/daily-pattern?point_id=${pointId}&weeks=4`);
    const pattern = patData.pattern || [];

    if (analyticsState.patternChart) {
      analyticsState.patternChart.destroy();
      analyticsState.patternChart = null;
    }

    const patCanvas = document.getElementById("patternChartCanvas");
    if (patCanvas && pattern.length > 0) {
      const DOW_LABELS = ["Pn", "Wt", "Śr", "Cz", "Pt", "So", "Nd"];
      const labels = pattern.map((p) => `${DOW_LABELS[p.day_of_week]} ${String(p.hour).padStart(2, "0")}:00`);
      const colors = pattern.map((p) => {
        const r = p.avg_ratio || 0;
        if (r >= 0.55) return "#f85149";
        if (r >= 0.30) return "#d29922";
        return "#3fb950";
      });

      analyticsState.patternChart = new Chart(patCanvas, {
        type: "bar",
        data: {
          labels: labels,
          datasets: [
            {
              label: "Średnia kongestia",
              data: pattern.map((p) => Math.round((p.avg_ratio || 0) * 100)),
              backgroundColor: colors.map((c) => c + "60"),
              borderColor: colors,
              borderWidth: 1,
              borderRadius: 3,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { intersect: false },
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: isLight ? "rgba(255,255,255,0.95)" : "rgba(18,23,32,0.95)",
              titleColor: isLight ? "#1a1d23" : "#e6edf3",
              bodyColor: isLight ? "#5a6270" : "#8b949e",
              borderColor: isLight ? "rgba(0,0,0,0.1)" : "rgba(255,255,255,0.1)",
              borderWidth: 1,
              callbacks: {
                label: (ctx) => `Kongestia: ${ctx.parsed.y}% (${ctx.raw > 55 ? "zator" : ctx.raw > 30 ? "zwolnienie" : "płynnie"})`,
                afterLabel: (ctx) => {
                  const p = pattern[ctx.dataIndex];
                  return `Próbek: ${p.samples || 0}`;
                },
              },
            },
          },
          scales: {
            x: {
              grid: { display: false },
              ticks: { maxTicksLimit: 24, maxRotation: 60, font: { size: 9 } },
            },
            y: {
              beginAtZero: true,
              max: 100,
              ticks: { callback: (v) => v + "%", font: { size: 10 } },
              grid: { color: gridColor },
            },
          },
        },
      });
    }
  } catch (e) {
    console.warn("Analytics pattern chart error:", e);
  }
}

// --- Integration with main app.js ---

// Override renderAll to also refresh analytics tab
const _origRenderAll = typeof renderAll === "function" ? renderAll : null;
if (_origRenderAll) {
  // Augment renderAll without breaking existing code
  window.renderAll = function () {
    _origRenderAll();
    // Only re-render risk scores inline (charts are loaded on tab switch)
    if (document.querySelector("#panel-analytics.active")) {
      renderRiskScores();
      renderWeather();
    }
  };
}

// Load analytics data when the tab is clicked
document.addEventListener("DOMContentLoaded", () => {
  const analyticsTab = document.querySelector('.tab[data-tab="analytics"]');
  if (analyticsTab) {
    analyticsTab.addEventListener("click", async () => {
      await loadAnalyticsData();
      renderAnalyticsPanel();
    });
  }
});

// Also load when refreshAll triggers (after init)
const _origRefreshAll = typeof refreshAll === "function" ? refreshAll : null;
if (_origRefreshAll) {
  window.refreshAll = async function () {
    await _origRefreshAll();
    // Silently preload analytics data
    try { await loadAnalyticsData(); } catch (e) { /* ignore */ }
    if (document.querySelector("#panel-analytics.active")) {
      renderRiskScores();
      renderWeather();
    }
  };
}
