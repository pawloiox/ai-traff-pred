import { useEffect, useState } from "react";
import { ArrowRight, BarChart3, Flag, LayoutDashboard, Truck } from "lucide-react";

/**
 * PortPulse — Landing Page (Light / Corporate)
 * -------------------------------------------------------------
 * Profesjonalny, jasny layout dla portów i firm logistycznych:
 * fotograficzny baner hero → jasna sekcja → diagram trzech dróg →
 * trzy korporacyjne karty bento z podglądami UI.
 *
 * Self-contained: React + Tailwind + lucide-react.
 * Owner: Osoba 1 (UI / Role / Widoki).
 */

const NAVY = "#0E3A76";
const LINE_IDLE = "#CBD5E1";

// Zdjęcie hero: lokalny plik w frontend/public/. Dopóki go nie wgrasz,
// baner korzysta z FALLBACK (Unsplash) przez onError.
const HERO_IMG = "/hero-port.jpg";
const HERO_FALLBACK =
  "https://images.unsplash.com/photo-1542314831-068cd1dbfeeb?auto=format&fit=crop&q=80&w=1600";

// Akcenty pobrane z palety zdjęcia portu:
// statek = morski błękit, dźwigi/kadłub = rdzawa czerwień, kontenery = bursztyn.
const CARDS = [
  {
    id: "dispatcher",
    eyebrow: "Firma / Dyspozytor",
    title: "Centrum orkiestracji ruchu",
    description:
      "Sterowanie w czasie rzeczywistym, orkiestracja bram terminalowych i predykcje wąskich gardeł oparte o AI.",
    cta: "Otwórz centrum",
    Icon: LayoutDashboard,
    color: "#1593C9", // morski błękit (statek)
    branch: "M600 40 C600 110 200 90 200 150",
  },
  {
    id: "driver",
    eyebrow: "Kierowca terminala",
    title: "Nawigacja i status slotu",
    description:
      "Mobilny asystent dla kierowców: nawigacja, dostępność slotów i miejsca w strefach buforowych.",
    cta: "Uruchom aplikację",
    Icon: Truck,
    color: "#C0432E", // rdzawa czerwień (dźwigi)
    branch: "M600 40 L600 150",
  },
  {
    id: "client",
    eyebrow: "Portal Klienta B2B",
    title: "Widoczność łańcucha dostaw",
    description:
      "Precyzyjne ETA kontenerów, pełna widoczność łańcucha dostaw i narzędzia zapobiegania demurrage.",
    cta: "Wejdź do portalu",
    Icon: BarChart3,
    color: "#DDA017", // bursztyn (kontenery)
    branch: "M600 40 C600 110 1000 90 1000 150",
  },
];

/* ============ małe, intuicyjne mini-wizualizacje ============ */
/* Każda w kolorze kreski prowadzącej do swojego przycisku.    */

// Dyspozytor — mini wykres słupkowy z siatką X/Y i etykietą VOL / H
function DispatcherMini({ color }) {
  const bars = [45, 70, 38, 85, 58, 74];
  return (
    <div className="relative h-full w-full">
      {/* siatka X/Y */}
      <div
        className="absolute inset-0 rounded"
        style={{
          backgroundImage:
            "linear-gradient(#EEF2F6 1px, transparent 1px), linear-gradient(90deg, #EEF2F6 1px, transparent 1px)",
          backgroundSize: "100% 25%, 16.666% 100%",
        }}
      />
      <span className="absolute right-0 top-0 font-mono text-[8px] font-medium tracking-wide text-slate-400">
        VOL / H
      </span>
      <div className="relative flex h-full items-end gap-1.5 pt-3.5">
        {bars.map((h, i) => (
          <div
            key={i}
            className="flex-1 rounded-sm"
            style={{ height: `${h}%`, backgroundColor: color, opacity: 0.9 }}
          />
        ))}
      </div>
    </div>
  );
}

// Kierowca — symulacja trasy nawigacji: świecący start, checkpointy, GATE 2
function DriverMini({ color }) {
  return (
    <div className="relative h-full w-full">
      <svg viewBox="0 0 200 56" className="h-full w-full" preserveAspectRatio="xMidYMid meet" fill="none">
        {/* trasa */}
        <path d="M12 46 C56 46 72 20 116 20 S176 22 190 16" stroke={color} strokeWidth="2.5" strokeLinecap="round" />
        {/* checkpointy (szare) */}
        <circle cx="72" cy="26" r="2.5" fill="#CBD5E1" />
        <circle cx="140" cy="20" r="2.5" fill="#CBD5E1" />
        {/* świecący węzeł startowy */}
        <circle cx="12" cy="46" r="8" fill={color} opacity="0.18" />
        <circle cx="12" cy="46" r="4" fill={color} />
        {/* cel */}
        <circle cx="190" cy="16" r="3.5" fill="#10B981" />
      </svg>
      <span className="absolute right-0 top-0 flex items-center gap-1 font-mono text-[8px] font-semibold text-emerald-600">
        <Flag className="h-2.5 w-2.5" strokeWidth={2.4} /> GATE 2
      </span>
    </div>
  );
}

// Klient B2B — mierniki ETA z etykietami mono (ID • % oraz godzina)
function ClientMini({ color }) {
  const rows = [
    { id: "MSK-7741", pct: 82, eta: "14:20" },
    { id: "TCLU-3052", pct: 54, eta: "15:05" },
    { id: "HLBU-9920", pct: 31, eta: "16:40" },
  ];
  return (
    <div className="flex h-full flex-col justify-center gap-1.5">
      {rows.map((r) => (
        <div key={r.id} className="space-y-1">
          <div className="flex items-center justify-between font-mono text-[8px] leading-none">
            <span className="font-medium text-slate-500">
              {r.id} • {r.pct}%
            </span>
            <span className="text-slate-400">ETA {r.eta}</span>
          </div>
          <div className="h-1 w-full overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full" style={{ width: `${r.pct}%`, backgroundColor: color }} />
          </div>
        </div>
      ))}
    </div>
  );
}

const PREVIEWS = {
  dispatcher: DispatcherMini,
  driver: DriverMini,
  client: ClientMini,
};

/* ===================== diagram trzech dróg ===================== */

function Pipeline({ active }) {
  const activeColor = active ? CARDS.find((c) => c.id === active).color : null;
  const trunkColor = activeColor ?? LINE_IDLE;
  return (
    <svg viewBox="0 0 1200 160" className="h-24 w-full sm:h-32" fill="none" preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id="trunkFade" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={trunkColor} stopOpacity="0" />
          <stop offset="0.55" stopColor={trunkColor} stopOpacity="0.5" />
          <stop offset="1" stopColor={trunkColor} stopOpacity="1" />
        </linearGradient>
      </defs>
      {/* pień wyłaniający się z dolnej krawędzi banera */}
      <line x1="600" y1="0" x2="600" y2="40" stroke="url(#trunkFade)" strokeWidth="3" strokeLinecap="round" className="transition-colors duration-300" />
      {CARDS.map((c) => {
        const on = active === c.id;
        return (
          <path
            key={c.id}
            d={c.branch}
            stroke={c.color}
            strokeWidth={on ? 4 : 3}
            strokeOpacity={on ? 1 : 0.5}
            strokeLinecap="round"
            className="transition-all duration-300"
          />
        );
      })}
      <circle cx="600" cy="40" r="6" fill="#ffffff" stroke={activeColor ?? "#94A3B8"} strokeWidth="3" className="transition-colors duration-300" />
    </svg>
  );
}

/* ============================ strona =========================== */

export default function LandingPage() {
  const [active, setActive] = useState(null);
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  const time = now.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" });

  return (
    <div className="min-h-screen w-full bg-white font-sans text-slate-900 antialiased">
      {/* =================== Baner fotograficzny =================== */}
      <div className="relative h-[460px] w-full overflow-hidden sm:h-[520px]">
        <img
          src={HERO_IMG}
          onError={(e) => {
            if (e.currentTarget.src !== HERO_FALLBACK) e.currentTarget.src = HERO_FALLBACK;
          }}
          alt="Terminal kontenerowy w porcie"
          className="absolute inset-0 h-full w-full object-cover"
        />
        {/* mocniejsza maska dla kontrastu białego tekstu + dół w biel */}
        <div className="absolute inset-0 bg-gradient-to-b from-slate-950/50 to-slate-900/30" />
        <div className="absolute inset-x-0 bottom-0 h-40 bg-gradient-to-b from-transparent to-white" />

        {/* Header na zdjęciu */}
        <header className="absolute inset-x-0 top-0 z-10">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
            <div className="flex items-center gap-2.5">
              <span className="h-2.5 w-2.5 rounded-full bg-white shadow" />
              <span className="text-lg font-extrabold tracking-tight text-white">
                Port<span className="text-white/70">Pulse</span>
              </span>
            </div>
            <div className="flex items-center gap-2.5 rounded-full border border-white/25 bg-white/10 px-3.5 py-1.5 text-xs font-medium text-white backdrop-blur-md">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-70" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
              </span>
              Status: Gdańsk | Gdynia | Szczecin — Online
              <span className="hidden font-mono text-white/60 sm:inline">{time}</span>
            </div>
          </div>
        </header>

        {/* Tekst hero */}
        <div className="relative z-[5] mx-auto flex h-full max-w-3xl flex-col items-center justify-center px-6 text-center">
          <h1 className="text-balance text-4xl font-extrabold leading-[1.08] tracking-tight text-white drop-shadow-sm sm:text-6xl">
            Żywy układ nerwowy logistyki portowej
          </h1>
          <p className="mt-5 max-w-2xl text-base leading-relaxed text-slate-100/90 sm:text-lg">
            Zintegrowana wizualizacja i predykcja kongestii drogowej w czasie
            rzeczywistym.
          </p>
        </div>
      </div>

      {/* =================== Sekcja jasna =================== */}
      <div className="bg-white">
        <div className="mx-auto max-w-6xl px-6">
          {/* Diagram trzech dróg wyłaniający się z dolnej krawędzi banera */}
          <div className="relative z-10 -mt-10">
            <Pipeline active={active} />
          </div>

          {/* Karty bento (light) */}
          <section className="grid grid-cols-1 gap-6 pb-16 sm:grid-cols-3">
            {CARDS.map((c) => {
              const on = active === c.id;
              const Preview = PREVIEWS[c.id];
              const { id, eyebrow, title, description, cta, Icon, color } = c;
              return (
                <div
                  key={id}
                  onMouseEnter={() => setActive(id)}
                  onMouseLeave={() => setActive(null)}
                  onFocusCapture={() => setActive(id)}
                  onBlurCapture={() => setActive(null)}
                  className="group flex flex-col rounded-3xl bg-white p-8 transition-all duration-300 sm:p-10"
                  style={{
                    // obramówka w kolorze ze zdjęcia (mocniejsza na hover)
                    border: `1.5px solid ${color}`,
                    borderColor: on ? color : `${color}66`,
                    transform: on ? "translateY(-6px)" : "none",
                    boxShadow: on
                      ? `0 24px 50px -24px ${color}80`
                      : "0 1px 3px rgba(15,23,42,0.06)",
                  }}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] font-bold uppercase tracking-[0.16em] text-slate-400">
                      {eyebrow}
                    </span>
                    <span
                      className="flex h-10 w-10 items-center justify-center rounded-xl transition-colors duration-300"
                      style={{ backgroundColor: `${color}14`, color }}
                    >
                      <Icon className="h-5 w-5" strokeWidth={1.8} />
                    </span>
                  </div>

                  {/* mała, intuicyjna mini-wizualizacja w kolorze ścieżki */}
                  <div className="mt-5 h-20 overflow-hidden rounded-xl border border-slate-100 bg-slate-50/70 px-3 py-2.5">
                    <Preview color={color} />
                  </div>

                  <div className="mt-6 flex-1 space-y-3">
                    <h3 className="text-lg font-bold" style={{ color: "#0F172A" }}>
                      {title}
                    </h3>
                    <p className="text-sm leading-relaxed" style={{ color: "#475569" }}>
                      {description}
                    </p>
                  </div>

                  {/* przycisk — solidny navy, ultra-gładki hover */}
                  <button
                    type="button"
                    className="mt-7 flex w-full items-center justify-center gap-2 rounded-xl bg-[#0E3A76] px-4 py-3 text-sm font-bold text-white shadow-sm transition-all duration-300 ease-in-out hover:bg-[#0A2A5C] hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-[#0E3A76] focus-visible:ring-offset-2"
                  >
                    {cta}
                    <ArrowRight className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-0.5" />
                  </button>
                </div>
              );
            })}
          </section>
        </div>

        <footer className="border-t border-slate-100 bg-[#F8FAFC] py-6 text-center text-xs text-slate-400">
          PortPulse · monitoring i predykcja ruchu portowego · Gdańsk · Gdynia · Szczecin
        </footer>
      </div>
    </div>
  );
}
