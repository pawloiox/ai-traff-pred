import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  Clock,
  Container,
  Search,
  ShieldCheck,
  TriangleAlert,
  UserRound,
} from "lucide-react";

/**
 * PortPulse — PORTAL KLIENTA B2B
 * -------------------------------------------------------------
 * Enterprise SaaS supply-chain visibility (styl Flexport): jasny
 * motyw, akcent indygo, KPI bento + tabela sledzenia przesylek.
 *
 * Owner: Osoba 1 (UI / Role / Widoki).
 */

const INDIGO = "#4F46E5";
const NAVY = "#0E3A76";
const fmtTime = (ts) => (ts ? new Date(ts * 1000).toLocaleTimeString("pl-PL") : "--:--:--");

const TONES = {
  ok: { color: "#10B981", bg: "#10B98115", label: "Na czas" },
  warn: { color: "#F59E0B", bg: "#F59E0B15", label: "Opóźnienie" },
  info: { color: INDIGO, bg: `${INDIGO}15`, label: "Slot" },
};

const SHIPMENTS = [
  {
    id: "MSK-7741", route: "Port Gdańsk (DCT)",
    situation: "W trasie — opóźnienie na ul. Marynarki Polskiej",
    sitTone: "warn", progress: 75, eta: "06:15", etaNote: "Opóźnienie +12 min", etaTone: "warn",
  },
  {
    id: "MSC-9920", route: "Port Gdynia (BCT)",
    situation: "Płynny dojazd — Estakada Kwiatkowskiego",
    sitTone: "ok", progress: 90, eta: "05:50", etaNote: "Na czas", etaTone: "ok",
  },
  {
    id: "HPL-4412", route: "Szczecin-Świnoujście",
    situation: "Oczekiwanie na parkingu buforowym",
    sitTone: "info", progress: 40, eta: "07:45", etaNote: "Zabezpieczony slot", etaTone: "info",
  },
  {
    id: "MAEU-3387", route: "Port Gdańsk (Baltic Hub)",
    situation: "Płynny dojazd — Trasa Sucharskiego",
    sitTone: "ok", progress: 62, eta: "06:40", etaNote: "Na czas", etaTone: "ok",
  },
  {
    id: "CMAU-5521", route: "Port Gdynia (BCT)",
    situation: "Zwolnienie — ul. Janka Wiśniewskiego",
    sitTone: "warn", progress: 54, eta: "07:10", etaNote: "Opóźnienie +8 min", etaTone: "warn",
  },
  {
    id: "OOLU-8132", route: "Port Gdańsk (DCT)",
    situation: "Rozładunek w toku — brama T2",
    sitTone: "ok", progress: 96, eta: "05:45", etaNote: "Na czas", etaTone: "ok",
  },
  {
    id: "TCLU-3052", route: "Szczecin-Świnoujście",
    situation: "Płynny dojazd — DK10",
    sitTone: "ok", progress: 28, eta: "08:20", etaNote: "Na czas", etaTone: "ok",
  },
  {
    id: "HLBU-6644", route: "Port Gdynia (BCT)",
    situation: "Oczekiwanie na slot bramy",
    sitTone: "info", progress: 47, eta: "07:30", etaNote: "Zabezpieczony slot", etaTone: "info",
  },
  {
    id: "MRKU-9001", route: "Port Gdańsk (DCT)",
    situation: "Zator — Tunel pod Martwą Wisłą",
    sitTone: "warn", progress: 70, eta: "06:55", etaNote: "Opóźnienie +18 min", etaTone: "warn",
  },
  {
    id: "SUDU-2270", route: "Szczecin-Świnoujście",
    situation: "Przygotowanie dokumentów celnych",
    sitTone: "info", progress: 84, eta: "06:05", etaNote: "Zabezpieczony slot", etaTone: "info",
  },
];

const KPIS = [
  { label: "Aktywne kontenery", value: "24", sub: "+3 dziś", icon: Container, tint: INDIGO, trend: true },
  { label: "Zagrożone sloty", value: "3", sub: "Wymaga uwagi", icon: TriangleAlert, tint: "#F59E0B" },
  { label: "Średni czas rozładunku", value: "18 min", sub: "Optymalny", icon: Clock, tint: "#10B981" },
  { label: "Potencjalne kary (demurrage)", value: "0 PLN", sub: "Bezpieczny", icon: ShieldCheck, tint: "#10B981" },
];

function Kpi({ k }) {
  const Icon = k.icon;
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition-shadow hover:shadow-md">
      <div className="flex items-center justify-between">
        <span className="grid h-10 w-10 place-items-center rounded-xl" style={{ backgroundColor: `${k.tint}15`, color: k.tint }}>
          <Icon className="h-5 w-5" strokeWidth={2} />
        </span>
        {k.trend && (
          <span className="inline-flex items-center gap-0.5 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-bold text-emerald-600">
            <ArrowUpRight className="h-3 w-3" /> {k.sub}
          </span>
        )}
      </div>
      <div className="mt-4 text-3xl font-extrabold tracking-tight" style={{ color: NAVY }}>{k.value}</div>
      <div className="mt-1 text-sm font-medium text-slate-500">{k.label}</div>
      {!k.trend && <div className="mt-2 text-xs font-semibold" style={{ color: k.tint }}>{k.sub}</div>}
    </div>
  );
}

function SituationCell({ tone, text }) {
  const t = TONES[tone];
  const Icon = tone === "ok" ? CheckCircle2 : tone === "warn" ? AlertTriangle : Clock;
  return (
    <div className="flex items-center gap-2">
      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg" style={{ backgroundColor: t.bg, color: t.color }}>
        <Icon className="h-4 w-4" strokeWidth={2.2} />
      </span>
      <span className="text-sm text-slate-600">{text}</span>
    </div>
  );
}

export default function ClientPortal() {
  const [lastPoll, setLastPoll] = useState(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    const load = () => fetch("/api/status").then((r) => r.json()).then((d) => setLastPoll(d.last_poll)).catch(() => {});
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return SHIPMENTS;
    return SHIPMENTS.filter((s) => `${s.id} ${s.route} ${s.situation}`.toLowerCase().includes(q));
  }, [query]);

  return (
    <div className="min-h-screen w-full bg-[#F8FAFC] font-sans text-slate-900 antialiased">
      {/* ===== TOP NAV ===== */}
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white px-5 py-3">
        <div className="mx-auto flex max-w-7xl items-center gap-4">
          <div className="flex shrink-0 items-center gap-2">
            <span className="relative flex h-2.5 w-2.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60" style={{ backgroundColor: INDIGO }} />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full" style={{ backgroundColor: INDIGO }} />
            </span>
            <span className="text-lg font-extrabold tracking-tight">Port<span className="text-slate-400">Pulse</span></span>
          </div>

          <div className="relative mx-2 hidden flex-1 sm:block">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input value={query} onChange={(e) => setQuery(e.target.value)}
              placeholder="Szukaj kontenera, numeru zlecenia, kierowcy…"
              className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2.5 pl-10 pr-4 text-sm text-slate-700 placeholder:text-slate-400 focus:border-indigo-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-indigo-100" />
          </div>

          <div className="flex shrink-0 items-center gap-3">
            <div className="hidden items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1.5 md:flex">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60" style={{ backgroundColor: INDIGO }} />
                <span className="relative inline-flex h-2 w-2 rounded-full" style={{ backgroundColor: INDIGO }} />
              </span>
              <span className="font-mono text-xs text-slate-500">Ostatni pomiar: {fmtTime(lastPoll)}</span>
            </div>
            <div className="flex items-center gap-2 rounded-full border border-slate-200 bg-white py-1 pl-1 pr-3">
              <span className="grid h-7 w-7 place-items-center rounded-full text-white" style={{ backgroundColor: NAVY }}>
                <UserRound className="h-4 w-4" />
              </span>
              <span className="hidden text-sm font-semibold text-slate-700 sm:block">Logistyka Sp. z o.o.</span>
            </div>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-5 py-6">
        {/* mobilny search */}
        <div className="relative mb-5 sm:hidden">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Szukaj kontenera, zlecenia…"
            className="w-full rounded-xl border border-slate-200 bg-white py-2.5 pl-10 pr-4 text-sm" />
        </div>

        {/* ===== KPI BENTO ===== */}
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {KPIS.map((k) => <Kpi key={k.label} k={k} />)}
        </section>

        {/* ===== TABELA PRZESYLEK ===== */}
        <section className="mt-6">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-lg font-bold" style={{ color: NAVY }}>Śledzenie przesyłek</h2>
            <span className="text-sm text-slate-400">{rows.length} aktywnych zleceń</span>
          </div>

          <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <div className="overflow-x-auto">
              <table className="min-w-full text-left">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50 text-[11px] font-bold uppercase tracking-wide text-slate-500">
                    <th className="px-5 py-3">ID ładunku</th>
                    <th className="px-5 py-3">Trasa / cel</th>
                    <th className="px-5 py-3">Pozycja & sytuacja drogowa</th>
                    <th className="px-5 py-3 w-48">Postęp dostawy</th>
                    <th className="px-5 py-3">ETA</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {rows.map((s) => {
                    const et = TONES[s.etaTone];
                    return (
                      <tr key={s.id} className="cursor-pointer transition-colors hover:bg-slate-50/80">
                        <td className="px-5 py-4">
                          <span className="font-mono text-sm font-bold" style={{ color: INDIGO }}>{s.id}</span>
                        </td>
                        <td className="px-5 py-4 text-sm font-semibold text-slate-800">{s.route}</td>
                        <td className="px-5 py-4"><SituationCell tone={s.sitTone} text={s.situation} /></td>
                        <td className="px-5 py-4">
                          <div className="flex items-center gap-2">
                            <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
                              <div className="h-full rounded-full" style={{ width: `${s.progress}%`, backgroundColor: INDIGO }} />
                            </div>
                            <span className="w-9 text-right font-mono text-xs font-bold text-slate-500">{s.progress}%</span>
                          </div>
                        </td>
                        <td className="px-5 py-4">
                          <div className="font-mono text-sm font-bold text-slate-800">{s.eta}</div>
                          <span className="mt-1 inline-block rounded-full px-2 py-0.5 text-[11px] font-bold" style={{ backgroundColor: et.bg, color: et.color }}>
                            {s.etaNote}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                  {rows.length === 0 && (
                    <tr><td colSpan={5} className="px-5 py-10 text-center text-sm text-slate-400">Brak wyników dla „{query}".</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <footer className="mt-8 text-center text-xs text-slate-400">
          PortPulse · widoczność łańcucha dostaw w czasie rzeczywistym
        </footer>
      </main>
    </div>
  );
}
