import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import {
  Activity,
  Bell,
  ChevronDown,
  CloudRain,
  Eye,
  Gauge as GaugeIcon,
  RefreshCw,
  ThermometerSun,
  TriangleAlert,
  TrendingDown,
  TrendingUp,
  Minus,
  Wind,
} from "lucide-react";

/**
 * PulsPort — Control Tower: widok FIRMA / DYSPOZYTOR (żywe dane)
 * -------------------------------------------------------------
 * Prawdziwa mapa Leaflet + kafelki TomTom (proxy /api) i panel
 * operacyjny: Stan / Wąskie gardła / Raporty / Predykcja / Analityka
 * (pogoda + historia kongestii + wzorzec dobowy). Wykresy w SVG.
 *
 * Owner: Osoba 1 (UI / Role / Widoki).
 */

const NAVY = "#0E3A76";
const CYAN = "#0891B2";
const CYAN_E = "#00F2FE";
const LEVEL = { ok: "#10B981", warning: "#F59E0B", critical: "#EF4444", unknown: "#94A3B8" };

const fmtTime = (ts) => (ts ? new Date(ts * 1000).toLocaleTimeString("pl-PL") : "--");
function agoLabel(ts) {
  if (!ts) return "";
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 10) return "teraz";
  if (s < 60) return `${s} s temu`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min temu`;
  return `${Math.floor(m / 60)} godz temu`;
}
const pct = (r) => `${Math.round((r || 0) * 100)}%`;
const levelOf = (r) => (r >= 0.6 ? "critical" : r >= 0.3 ? "warning" : "ok");

function trendWord(slopePer10min) {
  const s = (slopePer10min || 0) * 100; // pkt% / 10 min
  if (s >= 0.5) return { t: "narasta", c: LEVEL.critical, Icon: TrendingUp };
  if (s <= -0.5) return { t: "maleje", c: LEVEL.ok, Icon: TrendingDown };
  return { t: "stabilny", c: "#64748B", Icon: Minus };
}

/* Scoring ryzyka + pogoda — odwzorowanie z analytics.js (Osoba 3) */
const RISK_COLORS = { low: "#10B981", medium: "#F59E0B", high: "#EF4444", very_high: "#DC2626" };
const RISK_ICONS = { low: "✅", medium: "⚠️", high: "🔴", very_high: "🚨" };
const WEATHER_ICONS = {
  0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️", 45: "🌫️", 48: "🌫️",
  51: "🌦️", 53: "🌧️", 55: "🌧️", 61: "🌧️", 63: "🌧️", 65: "🌧️",
  71: "🌨️", 73: "🌨️", 75: "❄️", 77: "❄️", 80: "🌦️", 81: "🌧️", 82: "⛈️",
  85: "🌨️", 86: "❄️", 95: "⛈️", 96: "⛈️", 99: "⛈️",
};
const WEATHER_LABELS = {
  0: "Bezchmurnie", 1: "Prawie bezchmurnie", 2: "Częściowe zachmurzenie", 3: "Zachmurzenie całkowite",
  45: "Mgła", 48: "Mgła z szadzią", 51: "Mżawka lekka", 53: "Mżawka umiarkowana", 55: "Mżawka gęsta",
  61: "Deszcz lekki", 63: "Deszcz umiarkowany", 65: "Deszcz silny",
  71: "Śnieg lekki", 73: "Śnieg umiarkowany", 75: "Śnieg silny",
  80: "Przelotny deszcz", 81: "Deszcz przelotny um.", 82: "Ulewa",
  95: "Burza", 96: "Burza z gradem", 99: "Silna burza z gradem",
};
const wIcon = (c) => (c == null ? "❓" : WEATHER_ICONS[c] || "🌡️");
const wLabel = (c) => (c == null ? "Brak danych" : WEATHER_LABELS[c] || `Kod pogody: ${c}`);

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

/* ============================ wykresy SVG ============================ */

function AreaSpark({ data, color = CYAN, w = 300, h = 64 }) {
  if (!data || data.length < 2) return <div className="grid h-full place-items-center text-[10px] text-slate-300">brak danych</div>;
  const max = Math.max(...data, 0.001);
  const pts = data.map((v, i) => [(i / (data.length - 1)) * w, h - (v / max) * (h - 6) - 3]);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
  const gid = `g-${color.replace("#", "")}`;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-full w-full" preserveAspectRatio="none">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity="0.28" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${line} L${w} ${h} L0 ${h} Z`} fill={`url(#${gid})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Bars({ data, color = CYAN, h = 70 }) {
  if (!data || !data.length) return <div className="grid h-full place-items-center text-[10px] text-slate-300">brak danych</div>;
  const max = Math.max(...data, 0.001);
  return (
    <div className="flex h-full items-end gap-px" style={{ height: h }}>
      {data.map((v, i) => (
        <div key={i} className="flex-1 rounded-t-sm" style={{ height: `${Math.max(2, (v / max) * 100)}%`, backgroundColor: color, opacity: 0.85 }} title={pct(v)} />
      ))}
    </div>
  );
}

function Gauge100({ value, color, size = 60 }) {
  const r = (size - 8) / 2;
  const c = 2 * Math.PI * r;
  const off = c * (1 - value / 100);
  const cx = size / 2;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle cx={cx} cy={cx} r={r} fill="none" stroke="#E2E8F0" strokeWidth="6" />
      <circle
        cx={cx} cy={cx} r={r} fill="none" stroke={color} strokeWidth="6" strokeLinecap="round"
        strokeDasharray={c} strokeDashoffset={off}
        transform={`rotate(-90 ${cx} ${cx})`}
        style={{ transition: "stroke-dashoffset .5s ease" }}
      />
      <text x={cx} y={cx} dominantBaseline="central" textAnchor="middle" fontSize="14" fontWeight="800" fill={NAVY}>
        {value}%
      </text>
    </svg>
  );
}

/* ============================ panele ================================ */

function ArteryCard({ p }) {
  const ratio = p.congestion_ratio || 0;
  const lvl = p.level || levelOf(ratio);
  const color = LEVEL[lvl] || LEVEL.unknown;
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm transition-shadow hover:shadow-md">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-bold text-slate-900">{p.point_name}</h3>
          <p className="mt-0.5 truncate text-xs text-slate-400">{p.road || ""}</p>
        </div>
        <Gauge100 value={Math.round(ratio * 100)} color={color} />
      </div>

      {/* PREDKOSC — wyeksponowana */}
      <div className="mt-3 flex items-end justify-between rounded-xl bg-slate-50 px-3 py-2.5">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Prędkość</div>
          <div className="leading-none">
            <span className="text-2xl font-extrabold" style={{ color }}>
              {p.current_speed != null ? Math.round(p.current_speed) : "—"}
            </span>
            <span className="ml-1 text-sm font-semibold text-slate-500">km/h</span>
          </div>
        </div>
        <div className="text-right text-[11px] text-slate-400">
          swobodna<br /><span className="font-semibold text-slate-600">{p.free_flow_speed != null ? Math.round(p.free_flow_speed) : "—"} km/h</span>
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between">
        <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-bold" style={{ backgroundColor: `${color}1A`, color }}>
          <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: color }} />
          {lvl === "ok" ? "Płynnie" : lvl === "warning" ? "Zwolnienie" : lvl === "critical" ? "Zator" : "Brak danych"}
          {p.road_closure ? " · zamknięcie" : ""}
        </span>
      </div>

      {/* OSTATNI POMIAR */}
      <div className="mt-2.5 flex items-center justify-between border-t border-slate-100 pt-2 font-mono text-[10px] text-slate-400">
        <span>Ostatni pomiar: {fmtTime(p.ts)}</span>
        <span>{agoLabel(p.ts)}</span>
      </div>
    </div>
  );
}

function StanPanel({ points, lastPoll }) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-3 py-2 shadow-sm">
        <span className="text-xs font-semibold text-slate-500">Ostatni pomiar</span>
        <span className="font-mono text-xs font-bold text-slate-800">
          {fmtTime(lastPoll)} <span className="font-normal text-slate-400">· {agoLabel(lastPoll)}</span>
        </span>
      </div>
      {points.length === 0 && <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-400">Brak danych dla portu.</div>}
      {points.map((p) => <ArteryCard key={p.point_id} p={p} />)}
    </div>
  );
}

function BottlenecksPanel({ items }) {
  if (!items.length) return <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-400">Brak wąskich gardeł — ruch płynny.</div>;
  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500">Arterie z najwyższą kongestią (okno 60 min).</p>
      {items.map((it, i) => {
        const ratio = it.avg_ratio ?? it.max_ratio ?? it.congestion_ratio ?? 0;
        const color = LEVEL[levelOf(ratio)];
        return (
          <div key={(it.point_id || "") + i} className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
            <div className="flex items-center justify-between text-sm">
              <span className="truncate font-semibold text-slate-800"><span className="text-slate-400">#{i + 1}</span> {it.point_name || it.point_id}</span>
              <span className="ml-2 font-mono text-xs font-bold" style={{ color }}>{pct(ratio)}</span>
            </div>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100">
              <div className="h-full rounded-full" style={{ width: pct(ratio), backgroundColor: color }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ReportsPanel({ reports, onGenerate, generating }) {
  return (
    <div className="space-y-4">
      <button onClick={onGenerate} disabled={generating}
        className="flex w-full items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-bold text-white shadow-sm transition-opacity disabled:opacity-60"
        style={{ backgroundColor: NAVY }}>
        <Activity className="h-4 w-4" /> {generating ? "Generuję…" : "Wygeneruj raport globalny"}
      </button>
      {(!reports || !reports.length) && <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-400">Brak raportów.</div>}
      {(reports || []).map((r, i) => (
        <div key={(r.point_id || "") + i} className="rounded-2xl border border-slate-200 bg-white p-4 text-sm shadow-sm">
          <div className="flex items-center justify-between">
            <h3 className="font-bold text-slate-900">{r.point_name || r.point_id || "Raport"}</h3>
            <span className="rounded-full px-2 py-0.5 text-[10px] font-bold" style={{ backgroundColor: `${CYAN}1A`, color: CYAN }}>LLM</span>
          </div>
          <p className="mt-2 leading-relaxed text-slate-500">{r.summary || r.cause || r.text || r.description || "—"}</p>
          {r.point_id && (
            <a href={`/api/reports/${r.point_id}/pdf`} target="_blank" rel="noreferrer"
              className="mt-3 inline-block rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-bold text-white">Pobierz PDF</a>
          )}
        </div>
      ))}
    </div>
  );
}

function PredictionPanel({ predictions, horizon, setHorizon, mlActive }) {
  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex items-center justify-between text-sm">
          <span className="font-semibold text-slate-700">Horyzont prognozy</span>
          <span className="font-mono font-bold" style={{ color: CYAN }}>{horizon} h</span>
        </div>
        <input type="range" min="1" max="12" value={horizon} onChange={(e) => setHorizon(+e.target.value)} className="mt-3 w-full" style={{ accentColor: CYAN }} />
        <div className="mt-1 flex items-center gap-1.5 text-[10px] text-slate-400">
          <GaugeIcon className="h-3 w-3" /> {mlActive ? "Model ML (XGBoost) aktywny" : "Fallback: regresja liniowa"}
        </div>
      </div>

      {(!predictions || !predictions.length) && <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-400">Za mało danych do prognozy.</div>}

      {(predictions || []).map((p) => {
        const cur = p.current_ratio || 0;
        const pred = p.predicted_ratio || 0;
        const tw = trendWord(p.slope_per_10min);
        const predColor = LEVEL[levelOf(pred)];
        return (
          <div key={p.point_id} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <h3 className="truncate text-sm font-bold text-slate-900">{p.point_name}</h3>
            {/* TERAZ -> ZA N H — duzo bardziej czytelne */}
            <div className="mt-3 flex items-stretch gap-2">
              <div className="flex-1 rounded-xl bg-slate-50 px-3 py-2 text-center">
                <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Teraz</div>
                <div className="text-2xl font-extrabold" style={{ color: LEVEL[levelOf(cur)] }}>{pct(cur)}</div>
              </div>
              <div className="flex items-center text-slate-300">→</div>
              <div className="flex-1 rounded-xl px-3 py-2 text-center" style={{ backgroundColor: `${predColor}12` }}>
                <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Za {horizon} h</div>
                <div className="text-2xl font-extrabold" style={{ color: predColor }}>{pct(pred)}</div>
              </div>
            </div>
            {/* TREND slownie */}
            <div className="mt-3 flex items-center gap-2 text-xs font-semibold" style={{ color: tw.c }}>
              <tw.Icon className="h-4 w-4" />
              Trend: {tw.t}
              <span className="font-mono font-normal text-slate-400">
                ({(p.slope_per_10min * 100 >= 0 ? "+" : "")}{(p.slope_per_10min * 100).toFixed(1)} pkt%/10 min)
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function RiskCard({ r }) {
  const level = r.risk?.level || "low";
  const color = RISK_COLORS[level] || RISK_COLORS.low;
  const icon = RISK_ICONS[level] || "✅";
  const c = r.components || {};
  const comps = [
    ["Ruch", c.traffic_ratio_live],
    ["Anomalia", c.historical_anomaly],
    ["Pogoda", c.weather_penalty],
    ["Port", c.port_ship_penalty],
    ["Pora dnia", c.temporal_peak_penalty],
  ];
  const t = r.temporal || {};
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" style={{ borderLeft: `4px solid ${color}` }}>
      <div className="flex items-center gap-3">
        <span className="text-xl">{icon}</span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-bold text-slate-900">{r.point_name || r.point_id}</div>
          <div className="truncate text-xs text-slate-400">{r.road || ""}</div>
        </div>
        <span className="rounded-lg px-3 py-1 text-sm font-extrabold"
          style={{ backgroundColor: `${color}20`, color, border: `1px solid ${color}40` }}>{r.score}</span>
      </div>
      <div className="mt-2 text-sm font-semibold" style={{ color }}>{r.risk?.label || ""}</div>
      <div className="mt-3 space-y-1.5">
        {comps.map(([label, v]) => (
          <div key={label} className="flex items-center gap-2 text-[11px]">
            <span className="w-16 shrink-0 text-slate-500">{label}</span>
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
              <div className="h-full rounded-full" style={{ width: `${(v || 0) * 100}%`, backgroundColor: color, transition: "width .4s ease" }} />
            </div>
            <span className="w-9 shrink-0 text-right tabular-nums text-slate-400">{Math.round((v || 0) * 100)}%</span>
          </div>
        ))}
      </div>
      {(t.is_rush_hour || t.is_weekend || t.is_holiday) && (
        <div className="mt-3 flex flex-wrap gap-1.5 border-t border-slate-100 pt-2">
          {t.is_rush_hour && <span className="rounded-full bg-red-50 px-2 py-0.5 text-[10px] font-semibold text-red-600">🕐 Godzina szczytu</span>}
          {t.is_weekend && <span className="rounded-full bg-sky-50 px-2 py-0.5 text-[10px] font-semibold text-sky-600">📅 Weekend</span>}
          {t.is_holiday && <span className="rounded-full bg-violet-50 px-2 py-0.5 text-[10px] font-semibold text-violet-600">🎉 Święto</span>}
        </div>
      )}
    </div>
  );
}

function WeatherCard({ w, portName }) {
  const penalty = w.weather_penalty || 0;
  const pc = penalty > 0.5 ? RISK_COLORS.high : penalty > 0.2 ? RISK_COLORS.medium : RISK_COLORS.low;
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center gap-3">
        <span className="text-2xl">{wIcon(w.weather_code)}</span>
        <div>
          <div className="text-sm font-bold text-slate-900">{portName}</div>
          <div className="text-xs text-slate-400">{wLabel(w.weather_code)}</div>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 text-sm text-slate-600">
        <div className="flex items-center gap-2"><ThermometerSun className="h-4 w-4 text-amber-500" />{w.temperature != null ? `${w.temperature.toFixed(1)} °C` : "b.d."}</div>
        <div className="flex items-center gap-2"><CloudRain className="h-4 w-4 text-blue-500" />{w.rain != null ? `${w.rain.toFixed(1)} mm` : "0 mm"}</div>
        <div className="flex items-center gap-2"><Wind className="h-4 w-4 text-sky-500" />{w.wind_speed != null ? `${Math.round(w.wind_speed)} km/h` : "b.d."}</div>
        <div className="flex items-center gap-2"><Eye className="h-4 w-4 text-slate-500" />{w.visibility != null ? (w.visibility >= 1000 ? `${(w.visibility / 1000).toFixed(1)} km` : `${Math.round(w.visibility)} m`) : "b.d."}</div>
      </div>
      <div className="mt-3 border-t border-slate-100 pt-2 text-xs font-semibold" style={{ color: pc }}>
        Wpływ na ruch: {Math.round(penalty * 100)}%
        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
          <div className="h-full rounded-full" style={{ width: `${penalty * 100}%`, backgroundColor: pc }} />
        </div>
      </div>
    </div>
  );
}

function AnalyticsPanel({ riskScores, weather, portNames, history, dailyPattern }) {
  return (
    <div className="space-y-5">
      <section>
        <h3 className="mb-2 flex items-center gap-1.5 text-sm font-bold text-slate-900">🎯 Scoring Ryzyka Opóźnień</h3>
        {!riskScores.length ? (
          <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-400">Brak danych scoringu.</div>
        ) : (
          <div className="space-y-3">{riskScores.map((r) => <RiskCard key={r.point_id} r={r} />)}</div>
        )}
      </section>

      <section>
        <h3 className="mb-2 flex items-center gap-1.5 text-sm font-bold text-slate-900">🌤️ Pogoda w Portach</h3>
        {!weather.length ? (
          <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-400">Oczekiwanie na dane pogodowe…</div>
        ) : (
          <div className="space-y-3">{weather.map((w) => <WeatherCard key={w.port_id} w={w} portName={portNames[w.port_id] || w.port_id} />)}</div>
        )}
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <h3 className="mb-1 text-sm font-bold text-slate-900">📈 Historia kongestii (7 dni)</h3>
        <p className="mb-2 text-[11px] text-slate-400">Średnia dla portu</p>
        <div className="h-16"><AreaSpark data={history} color={CYAN} /></div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <h3 className="mb-1 text-sm font-bold text-slate-900">📅 Wzorzec dobowy</h3>
        <p className="mb-2 text-[11px] text-slate-400">Średnia kongestia wg godziny (0–23)</p>
        <Bars data={dailyPattern} color={NAVY} />
        <div className="mt-1 flex justify-between font-mono text-[9px] text-slate-300"><span>00</span><span>06</span><span>12</span><span>18</span><span>23</span></div>
      </section>
    </div>
  );
}

/* ============================ dashboard ============================ */

const TABS = ["Stan", "Wąskie gardła", "Raporty", "Predykcja", "Analityka"];

export default function DispatcherDashboard() {
  const [tab, setTab] = useState("Stan");
  const [ports, setPorts] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [flow, setFlow] = useState(true);
  const [incidents, setIncidents] = useState(true);
  const [horizon, setHorizon] = useState(1);
  const [generating, setGenerating] = useState(false);

  const [status, setStatus] = useState({ last_poll: null, points: [] });
  const [predictions, setPredictions] = useState([]);
  const [bottlenecks, setBottlenecks] = useState([]);
  const [reports, setReports] = useState([]);
  const [weather, setWeather] = useState([]);
  const [history, setHistory] = useState([]);
  const [dailyPattern, setDailyPattern] = useState([]);
  const [riskScores, setRiskScores] = useState([]);

  const mapRef = useRef(null);
  const layersRef = useRef({});
  const markersRef = useRef({});
  const tilesRef = useRef(null);
  const horizonRef = useRef(horizon);
  horizonRef.current = horizon;

  const selectedPort = ports.find((p) => p.id === selectedId) || ports[0] || null;

  /* --- init: porty + mapa --- */
  useEffect(() => {
    let cancelled = false;
    let intervalId;
    (async () => {
      try {
        const pd = await getJSON("/api/ports");
        if (cancelled) return;
        setPorts(pd.ports);
        setSelectedId(pd.ports[0].id);
        tilesRef.current = pd.tiles;
        initMap(pd);
        await refreshAll();
        intervalId = setInterval(refreshAll, 30000);
      } catch (e) {
        console.error("Init blad:", e);
      }
    })();
    return () => {
      cancelled = true;
      clearInterval(intervalId);
      if (mapRef.current) { mapRef.current.remove(); mapRef.current = null; }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function initMap(pd) {
    if (mapRef.current) return;
    const sp = pd.ports[0];
    const bounds = L.latLngBounds([53.2, 14.0], [54.9, 19.1]);
    const map = L.map("disp-map", { zoomControl: true, maxBounds: bounds.pad(0.05), maxBoundsViscosity: 1.0, minZoom: 8 })
      .setView([sp.center.lat, sp.center.lon], sp.zoom || 12);
    const basemap = L.tileLayer(pd.tiles.basemap_light || pd.tiles.basemap, { maxZoom: 22, attribution: "&copy; TomTom" }).addTo(map);
    const flowL = L.tileLayer(pd.tiles.flow, { maxZoom: 22, opacity: 0.9 });
    const incL = L.tileLayer(pd.tiles.incidents, { maxZoom: 22 });
    flowL.addTo(map);
    incL.addTo(map);
    layersRef.current = { basemap, flow: flowL, incidents: incL };

    pd.ports.forEach((port) =>
      port.points.forEach((pt) => {
        const m = L.circleMarker([pt.lat, pt.lon], { radius: 8, color: "#0b0f17", weight: 1.5, fillColor: LEVEL.unknown, fillOpacity: 0.95 }).addTo(map);
        m.bindPopup(`<strong>${pt.name}</strong><br/>${pt.road || ""}`);
        markersRef.current[pt.id] = m;
      })
    );
    setTimeout(() => map.invalidateSize(), 250);
    mapRef.current = map;
  }

  async function refreshAll() {
    const h = horizonRef.current;
    const res = await Promise.allSettled([
      getJSON("/api/status"),
      getJSON(`/api/predictions?horizon=${h}`),
      getJSON("/api/bottlenecks?window=60&limit=15"),
      getJSON("/api/reports?limit=12"),
      getJSON("/api/weather"),
      getJSON("/api/analytics/congestion-history?days=7"),
      getJSON("/api/risk-scores"),
    ]);
    const v = (i, f) => (res[i].status === "fulfilled" ? res[i].value : f);
    const st = v(0, { last_poll: null, points: [] });
    setStatus(st);
    setPredictions(v(1, { predictions: [] }).predictions);
    setBottlenecks(v(2, { bottlenecks: [] }).bottlenecks);
    setReports(v(3, { reports: [] }).reports);
    setWeather(v(4, { weather: [] }).weather);
    setHistory(v(5, { history: [] }).history);
    setRiskScores(v(6, { risk_scores: [] }).risk_scores);
    updateMarkers(st.points);
  }

  function updateMarkers(pts) {
    pts.forEach((p) => {
      const m = markersRef.current[p.point_id];
      if (!m) return;
      const lvl = p.level || "unknown";
      m.setStyle({ fillColor: LEVEL[lvl] || LEVEL.unknown });
      m.setRadius(lvl === "critical" ? 11 : 8);
      m.setPopupContent(
        `<strong>${p.point_name}</strong><br/>${p.road || ""}<br/>Kongestia: <b>${pct(p.congestion_ratio)}</b><br/>Prędkość: ${p.current_speed != null ? Math.round(p.current_speed) : "—"} km/h`
      );
    });
  }

  /* --- horyzont -> refetch predykcji --- */
  useEffect(() => {
    if (!ports.length) return;
    getJSON(`/api/predictions?horizon=${horizon}`).then((d) => setPredictions(d.predictions)).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [horizon]);

  /* --- zmiana portu: recenter + wzorzec dobowy --- */
  useEffect(() => {
    if (!selectedPort) return;
    if (mapRef.current) {
      mapRef.current.setView([selectedPort.center.lat, selectedPort.center.lon], selectedPort.zoom || 12);
      setTimeout(() => mapRef.current.invalidateSize(), 200);
    }
    const firstPoint = selectedPort.points?.[0]?.id;
    if (firstPoint) {
      getJSON(`/api/analytics/daily-pattern?point_id=${firstPoint}&weeks=4`)
        .then((d) => {
          const byHour = Array(24).fill(0);
          const cnt = Array(24).fill(0);
          (d.pattern || []).forEach((row) => { byHour[row.hour] += row.avg_ratio; cnt[row.hour] += 1; });
          setDailyPattern(byHour.map((s, i) => (cnt[i] ? s / cnt[i] : 0)));
        })
        .catch(() => setDailyPattern([]));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, ports.length]);

  /* --- toggle warstw --- */
  useEffect(() => {
    const ls = layersRef.current, map = mapRef.current;
    if (!map || !ls.flow) return;
    flow ? ls.flow.addTo(map) : map.removeLayer(ls.flow);
  }, [flow]);
  useEffect(() => {
    const ls = layersRef.current, map = mapRef.current;
    if (!map || !ls.incidents) return;
    incidents ? ls.incidents.addTo(map) : map.removeLayer(ls.incidents);
  }, [incidents]);

  async function generateReport() {
    setGenerating(true);
    try {
      await fetch("/api/reports/on-demand", { method: "POST" });
      const d = await getJSON("/api/reports?limit=12");
      setReports(d.reports);
    } catch (e) { console.error(e); }
    finally { setGenerating(false); }
  }

  /* --- dane filtrowane po porcie --- */
  const portPointIds = useMemo(() => new Set((selectedPort?.points || []).map((p) => p.id)), [selectedPort]);
  const statusPts = status.points.filter((p) => portPointIds.has(p.point_id));
  const predPts = predictions.filter((p) => portPointIds.has(p.point_id));
  const bottlePts = bottlenecks.filter((b) => !b.point_id || portPointIds.has(b.point_id));
  const riskPts = riskScores.filter((r) => r.port_id === selectedPort?.id);
  const portNames = useMemo(() => Object.fromEntries(ports.map((p) => [p.id, p.name])), [ports]);
  const mlActive = predictions[0]?.ml_active ?? false;

  // historia: srednia avg_ratio per hour_ts dla punktow portu
  const historyData = useMemo(() => {
    const byTs = {};
    history.filter((r) => portPointIds.has(r.point_id)).forEach((r) => {
      byTs[r.hour_ts] = byTs[r.hour_ts] || [];
      byTs[r.hour_ts].push(r.avg_ratio);
    });
    return Object.keys(byTs).sort((a, b) => a - b).map((k) => byTs[k].reduce((s, x) => s + x, 0) / byTs[k].length);
  }, [history, portPointIds]);

  return (
    <div className="flex h-screen w-full flex-col bg-[#F8FAFC] font-sans text-slate-900 antialiased">
      {/* TOP NAV */}
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white px-5 py-3">
        <div className="flex items-center gap-2.5">
          <span className="relative flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60" style={{ backgroundColor: CYAN_E }} />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full" style={{ backgroundColor: CYAN_E }} />
          </span>
          <span className="text-lg font-extrabold tracking-tight">Puls<span className="text-slate-400">Port</span></span>
        </div>

        <div className="flex items-center gap-3">
          <div className="relative">
            <select value={selectedId || ""} onChange={(e) => setSelectedId(e.target.value)}
              className="appearance-none rounded-lg border border-slate-200 bg-white py-2 pl-3 pr-9 text-sm font-semibold text-slate-800 shadow-sm focus:outline-none">
              {ports.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          </div>
          {[["Natężenie", flow, setFlow], ["Incydenty", incidents, setIncidents]].map(([label, val, set]) => (
            <label key={label} className="flex cursor-pointer items-center gap-2 text-sm font-medium text-slate-600">
              <input type="checkbox" checked={val} onChange={(e) => set(e.target.checked)} className="h-4 w-4 rounded border-slate-300" style={{ accentColor: CYAN }} />
              {label}
            </label>
          ))}
        </div>

        <div className="flex items-center gap-2.5">
          <button className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50">
            <Bell className="h-4 w-4" /> Powiadomienia
          </button>
          <button onClick={refreshAll} className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold text-white shadow-sm" style={{ backgroundColor: NAVY }}>
            <RefreshCw className="h-4 w-4" /> Odśwież
          </button>
          <div className="hidden items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 sm:flex">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60" style={{ backgroundColor: CYAN_E }} />
              <span className="relative inline-flex h-2 w-2 rounded-full" style={{ backgroundColor: CYAN_E }} />
            </span>
            <span className="font-mono text-xs text-slate-500">Ostatni pomiar: {fmtTime(status.last_poll)}</span>
          </div>
        </div>
      </header>

      {/* WORKSPACE */}
      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        {/* MAPA */}
        <main className="relative min-h-[42vh] flex-1 p-4 lg:min-h-0">
          <div id="disp-map" className="h-full w-full overflow-hidden rounded-2xl border border-slate-200" style={{ background: "#eef2f6" }} />
          {/* LEGENDA glassmorphism */}
          <div className="pointer-events-none absolute bottom-7 left-7 z-[500] rounded-2xl border border-white/10 bg-slate-900/80 p-4 text-white shadow-xl backdrop-blur-xl">
            <div className="mb-2.5 text-[11px] font-bold uppercase tracking-[0.16em] text-white/60">Legenda</div>
            <div className="space-y-1.5 text-xs">
              {[["Płynnie", LEVEL.ok], ["Zwolnienie", LEVEL.warning], ["Zator / zamknięcie", LEVEL.critical]].map(([t, c]) => (
                <div key={t} className="flex items-center gap-2.5"><span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: c }} /><span className="text-white/85">{t}</span></div>
              ))}
              <div className="my-2 h-px bg-white/10" />
              <div className="flex items-center gap-2.5"><TriangleAlert className="h-3.5 w-3.5" style={{ color: LEVEL.warning }} /><span className="text-white/85">Zdarzenie TomTom</span></div>
            </div>
          </div>
        </main>

        {/* SIDEBAR */}
        <aside className="flex w-full flex-col border-t border-slate-200 bg-white lg:w-96 lg:border-l lg:border-t-0">
          <div className="flex gap-0.5 overflow-x-auto border-b border-slate-200 px-3 pt-3">
            {TABS.map((t) => {
              const active = tab === t;
              return (
                <button key={t} onClick={() => setTab(t)} className="relative whitespace-nowrap px-2.5 pb-2.5 pt-1 text-xs font-bold transition-colors" style={{ color: active ? CYAN : "#64748B" }}>
                  {t}
                  {active && <span className="absolute inset-x-1 -bottom-px h-0.5 rounded-full" style={{ backgroundColor: CYAN }} />}
                </button>
              );
            })}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {tab === "Stan" && <StanPanel points={statusPts} lastPoll={status.last_poll} />}
            {tab === "Wąskie gardła" && <BottlenecksPanel items={bottlePts} />}
            {tab === "Raporty" && <ReportsPanel reports={reports} onGenerate={generateReport} generating={generating} />}
            {tab === "Predykcja" && <PredictionPanel predictions={predPts} horizon={horizon} setHorizon={setHorizon} mlActive={mlActive} />}
            {tab === "Analityka" && <AnalyticsPanel riskScores={riskPts} weather={weather} portNames={portNames} history={historyData} dailyPattern={dailyPattern} />}
          </div>
        </aside>
      </div>
    </div>
  );
}
