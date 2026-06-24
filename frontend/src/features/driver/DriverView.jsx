import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  MapPin,
  Navigation,
  ParkingSquare,
  Pencil,
  Route,
  Truck,
} from "lucide-react";

/**
 * PulsePort — KIEROWCA TERMINALA (mobilny HUD)
 * -------------------------------------------------------------
 * In-cab HUD: gigantyczna typografia, wielkie touch-targety,
 * sygnalizacja swietlna. Kierowca ustawia OBSZAR (port) i CEL
 * (punkt/brama); hero i alternatywy dopasowuja sie do wyboru.
 *
 * Dane na zywo (/api proxy). Tryb SYMULACJI zatoru domyslnie ON
 * (noca realnie jest "trasa wolna").  Owner: Osoba 1.
 */

const SIG = { ok: "#10B981", warning: "#F59E0B", critical: "#EF4444" };
const NAVY = "#0E3A76";

const fmtTime = (ts) => (ts ? new Date(ts * 1000).toLocaleTimeString("pl-PL") : "--:--:--");
const levelWord = (lvl) => (lvl === "critical" ? "ZATOR" : lvl === "warning" ? "ZWOLNIENIE" : "PŁYNNY RUCH");
const timeFor = (r) => Math.round(8 + (r || 0) * 26);

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

function RouteProgress({ level, jamPos = 0.55 }) {
  const color = SIG[level] || SIG.ok;
  const showJam = level !== "ok";
  return (
    <div className="relative mt-6 h-3 w-full rounded-full bg-white/25">
      <div className="absolute left-0 top-0 h-3 rounded-full bg-white/80" style={{ width: "16%" }} />
      {showJam && <div className="absolute top-0 h-3 rounded-full bg-white/95" style={{ left: `${jamPos * 100}%`, width: "26%" }} />}
      <div className="absolute -top-3 -translate-x-1/2" style={{ left: "16%" }}>
        <div className="grid h-9 w-9 place-items-center rounded-full bg-white shadow-lg" style={{ color }}>
          <Truck className="h-5 w-5" strokeWidth={2.4} />
        </div>
      </div>
      {showJam && (
        <div className="absolute -top-2.5 -translate-x-1/2" style={{ left: `${(jamPos + 0.13) * 100}%` }}>
          <div className="grid h-8 w-8 place-items-center rounded-full bg-white shadow-lg" style={{ color }}>
            <AlertTriangle className="h-4 w-4" strokeWidth={2.6} />
          </div>
        </div>
      )}
      <div className="absolute -top-3 right-0 translate-x-1/2">
        <div className="grid h-9 w-9 place-items-center rounded-full bg-white text-slate-800 shadow-lg">
          <MapPin className="h-5 w-5" strokeWidth={2.4} />
        </div>
      </div>
    </div>
  );
}

function InfoStrip({ icon: Icon, color, title, value }) {
  return (
    <div className="flex items-center gap-4 rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-sm">
      <span className="grid h-12 w-12 shrink-0 place-items-center rounded-xl" style={{ backgroundColor: `${color}1A`, color }}>
        <Icon className="h-6 w-6" strokeWidth={2.2} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold text-slate-500">{title}</div>
        <div className="truncate text-lg font-extrabold text-slate-900">{value}</div>
      </div>
    </div>
  );
}

export default function DriverView() {
  const [demo, setDemo] = useState(true);
  const [ports, setPorts] = useState([]);
  const [portId, setPortId] = useState(null);
  const [pointId, setPointId] = useState(null);
  const [editing, setEditing] = useState(false);
  const [status, setStatus] = useState({ last_poll: null, points: [] });
  const [ack, setAck] = useState(null);
  const timerRef = useRef(null);

  useEffect(() => {
    getJSON("/api/ports").then((d) => {
      setPorts(d.ports);
      setPortId(d.ports[0].id);
      setPointId(d.ports[0].points[0]?.id || null);
    }).catch(() => {});
    const load = () => getJSON("/api/status").then(setStatus).catch(() => {});
    load();
    timerRef.current = setInterval(load, 30000);
    return () => clearInterval(timerRef.current);
  }, []);

  const selectedPort = ports.find((p) => p.id === portId) || ports[0] || null;
  const destPoints = selectedPort?.points || [];
  const destPoint = destPoints.find((p) => p.id === pointId) || destPoints[0] || null;

  const statusBy = {};
  (status.points || []).forEach((p) => { statusBy[p.point_id] = p; });
  const destStatus = destPoint ? statusBy[destPoint.id] : null;

  // scenariusz: symulacja krytyczna (na wybranym celu) LUB realny stan celu
  const scenario = demo
    ? { level: "critical", name: (destPoint?.name || "TRASA SUCHARSKIEGO").toUpperCase(), delay: 22 }
    : destStatus
      ? { level: destStatus.level || "ok", name: (destStatus.point_name || destPoint?.name || "").toUpperCase(), delay: Math.round((destStatus.congestion_ratio || 0) * 28) }
      : { level: "ok", name: (destPoint?.name || "TRASA WOLNA").toUpperCase(), delay: 0 };

  const color = SIG[scenario.level] || SIG.ok;
  const clear = scenario.level === "ok";
  const HeroIcon = clear ? Navigation : scenario.level === "warning" ? Route : AlertTriangle;
  const headline = clear ? "JEDŹ TERAZ" : `${levelWord(scenario.level)}: ${scenario.name}`;

  // alternatywy = pozostale punkty wybranego portu (live)
  const alts = destPoints
    .filter((p) => p.id !== destPoint?.id)
    .map((p) => ({ p, st: statusBy[p.id] }))
    .slice(0, 2);

  return (
    <div className="min-h-screen w-full bg-[#F8FAFC] font-sans text-slate-900 antialiased">
      <div className="mx-auto flex min-h-screen w-full max-w-[480px] flex-col">

        {/* HEADER */}
        <header className="sticky top-0 z-20 flex items-center justify-between border-b border-slate-200 bg-white/95 px-5 py-3 backdrop-blur">
          <div className="flex items-center gap-2">
            <span className="relative flex h-2.5 w-2.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
            </span>
            <span className="text-base font-extrabold tracking-tight">Pulse<span className="text-slate-400">Port</span></span>
          </div>
          <div className="text-right">
            <div className="text-xs font-bold text-slate-700">{selectedPort?.name || "—"}</div>
            <div className="font-mono text-[11px] text-slate-400">Ostatni pomiar: {fmtTime(status.last_poll)}</div>
          </div>
        </header>

        {/* ===== USTAW CEL (pole + przycisk) ===== */}
        <section className="px-5 pt-4">
          <button onClick={() => setEditing((e) => !e)}
            className="flex w-full items-center gap-3 rounded-2xl border border-slate-200 bg-white px-5 py-4 text-left shadow-sm active:scale-[0.99]">
            <span className="grid h-12 w-12 shrink-0 place-items-center rounded-xl" style={{ backgroundColor: `${NAVY}14`, color: NAVY }}>
              <MapPin className="h-6 w-6" strokeWidth={2.4} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-xs font-semibold uppercase tracking-wide text-slate-400">Dokąd jedziesz?</span>
              <span className="block truncate text-lg font-extrabold text-slate-900">
                {destPoint?.name || "Wybierz cel"}
              </span>
              <span className="block truncate text-xs text-slate-400">Obszar: {selectedPort?.name || "—"}</span>
            </span>
            <Pencil className="h-5 w-5 shrink-0 text-slate-400" />
          </button>

          {editing && (
            <div className="mt-3 space-y-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <label className="block">
                <span className="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Obszar (port)</span>
                <div className="relative">
                  <select value={portId || ""} onChange={(e) => { setPortId(e.target.value); const np = ports.find((p) => p.id === e.target.value); setPointId(np?.points[0]?.id || null); }}
                    className="h-14 w-full appearance-none rounded-xl border border-slate-200 bg-white px-4 pr-10 text-lg font-bold text-slate-800">
                    {ports.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                  </select>
                  <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
                </div>
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Cel (brama / arteria)</span>
                <div className="relative">
                  <select value={pointId || ""} onChange={(e) => setPointId(e.target.value)}
                    className="h-14 w-full appearance-none rounded-xl border border-slate-200 bg-white px-4 pr-10 text-lg font-bold text-slate-800">
                    {destPoints.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                  </select>
                  <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
                </div>
              </label>
              <button onClick={() => setEditing(false)}
                className="h-14 w-full rounded-xl text-lg font-black uppercase tracking-wide text-white active:scale-[0.99]" style={{ backgroundColor: NAVY }}>
                Zatwierdź cel
              </button>
            </div>
          )}
        </section>

        {/* tryb symulacja / na zywo */}
        <button onClick={() => setDemo((d) => !d)}
          className="mx-5 mt-3 self-start rounded-full border border-slate-200 bg-white px-3 py-1 text-[11px] font-bold text-slate-500 shadow-sm">
          {demo ? "● SYMULACJA ZATORU — kliknij, by dane na żywo" : "○ DANE NA ŻYWO — kliknij, by symulacja"}
        </button>

        {/* HERO */}
        <section className="px-5 pt-3">
          <div className="rounded-3xl p-7 text-white shadow-xl" style={{ backgroundColor: color }}>
            <div className="flex items-center gap-3">
              <span className="grid h-14 w-14 place-items-center rounded-2xl bg-white/20"><HeroIcon className="h-8 w-8" strokeWidth={2.6} /></span>
              <span className="text-sm font-black uppercase tracking-[0.2em] text-white/80">{clear ? "Status trasy" : "Alert ruchu"}</span>
            </div>
            <h1 className="mt-5 text-4xl font-black leading-[1.02] tracking-tight">{headline}</h1>
            <div className="mt-4 flex items-baseline gap-3">
              {!clear && <span className="text-6xl font-black leading-none">+{scenario.delay}</span>}
              <span className="text-xl font-extrabold uppercase leading-tight text-white/90">
                {clear ? "BRAK OPÓŹNIEŃ DO CELU" : "MIN OPÓŹNIENIA DO CELU"}
              </span>
            </div>
            <RouteProgress level={scenario.level} />
            <div className="mt-2 flex justify-between text-[11px] font-bold uppercase tracking-wide text-white/70">
              <span>Ty</span><span>{clear ? "Trasa wolna" : "Korek"}</span><span>Cel</span>
            </div>
          </div>
        </section>

        {/* ALTERNATYWY */}
        <section className="space-y-3 px-5 pt-5">
          {alts.map(({ p, st }) => {
            const lvl = st?.level || "ok";
            const c = SIG[lvl] || SIG.ok;
            return (
              <InfoStrip key={p.id} icon={lvl === "ok" ? CheckCircle2 : lvl === "warning" ? Route : AlertTriangle}
                color={c} title={p.name} value={`${levelWord(lvl)} · ${timeFor(st?.congestion_ratio)} min`} />
            );
          })}
          <InfoStrip icon={ParkingSquare} color={NAVY} title="Parking buforowy · ul. Ku Ujściu" value="45 MIEJSC WOLNYCH" />
        </section>

        {/* PRZYCISKI */}
        <div className="mt-auto space-y-3 px-5 pb-6 pt-6">
          {ack && <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-center text-sm font-bold text-emerald-700">{ack}</div>}
          <button onClick={() => setAck(`Trasa do „${destPoint?.name || "celu"}" przeliczona — nawigacja zaktualizowana.`)}
            className="flex h-20 w-full items-center justify-center gap-3 rounded-2xl text-xl font-black uppercase tracking-wide text-white shadow-lg transition-transform active:scale-[0.98]" style={{ backgroundColor: NAVY }}>
            <Navigation className="h-7 w-7" strokeWidth={2.6} /> Zaakceptuj zmianę trasy
          </button>
          <button onClick={() => setAck("Kierunek: parking buforowy ul. Ku Ujściu (45 miejsc).")}
            className="flex h-16 w-full items-center justify-center gap-3 rounded-2xl bg-slate-200 text-lg font-black uppercase tracking-wide text-slate-700 transition-transform active:scale-[0.98]">
            <ParkingSquare className="h-6 w-6" strokeWidth={2.6} /> Zjeżdżam na parking buforowy
          </button>
        </div>
      </div>
    </div>
  );
}
