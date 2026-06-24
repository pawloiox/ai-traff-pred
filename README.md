# PulsePort

**Żywy układ nerwowy logistyki portowej** — platforma czasu rzeczywistego do
monitorowania i predykcji kongestii drogowej na drogach dojazdowych do terminali
w **Gdańsku, Gdyni i Szczecinie-Świnoujściu**.

PulsePort zamienia rozproszone, surowe dane o ruchu (TomTom, miejskie systemy ITS,
pogoda, harmonogramy statków) w jeden, predykcyjny obraz sytuacji — dostępny w trzech
dopasowanych widokach: **Dyspozytora portu**, **Kierowcy ciężarówki** i **Klienta B2B**.

---

## 1. Opis problemu

Terminale portowe to wąskie gardła całego morskiego łańcucha dostaw. Sam plac
przeładunkowy bywa zoptymalizowany, ale **„ostatni kilometr" — drogi dojazdowe poza
bramą terminala — pozostaje czarną dziurą informacyjną**.

Jak wygląda to dziś:

- **Kierowca** rusza do portu „w ciemno". O zatorze na Trasie Sucharskiego czy Estakadzie
  Kwiatkowskiego dowiaduje się dopiero stojąc w nim. Spóźnia się na okno czasowe (slot)
  w bramie i traci kolejny.
- **Dyspozytor / terminal** reaguje, a nie przewiduje. Informacja o korku przychodzi
  z opóźnieniem, decyzje (przesunięcie slotu, skierowanie do strefy buforowej) podejmowane
  są ad hoc, telefonicznie.
- **Klient (spedytor / firma logistyczna)** nie wie, czy kontener dojedzie na czas. Ryzyko
  **demurrage / detention** (kar za przetrzymanie kontenera) jest wykrywane po fakcie.
- Dane istnieją, ale są **rozproszone i niepołączone**: TomTom osobno, miejskie systemy
  ITS (TRISTAR w Gdyni, ZDiTM w Szczecinie) osobno, pogoda osobno, awizacje statków osobno.
  Nikt nie łączy ich w jeden, predykcyjny sygnał.

**Efekt:** puste przebiegi, przekroczone sloty, kary umowne, korki wokół bram i brak
wspólnej „prawdy" o sytuacji dla wszystkich stron procesu.

---

## 2. Dla kogo jest to rozwiązanie

PulsePort obsługuje **trzy persony** jednego procesu — każda dostaje dedykowany widok
zasilany tym samym silnikiem danych:

| Odbiorca | Rola w procesie | Co zyskuje |
| --- | --- | --- |
| **Dyspozytor / Operator terminala** (klient docelowy) | Zarządza ruchem ciężarówek i bramami | Wczesne ostrzeganie o zatorach, predykcja 1–12 h, scoring ryzyka opóźnień, raporty operacyjne |
| **Kierowca / Przewoźnik** | Dojazd do bramy w oknie czasowym | Rekomendacja „jedź / poczekaj", status slotu, najlepsza trasa, strefa buforowa |
| **Klient B2B (spedytor, firma logistyczna)** | Odpowiada za terminowość dostaw | Widoczność łańcucha dostaw, ETA kontenerów, wczesne ostrzeganie o ryzyku demurrage |

**Interesariusze procesu:** zarządy portów i terminali (DCT/Baltic Hub, BCT), miejskie
zarządy dróg (ZDiZ, ZDiTM, TRISTAR), przewoźnicy drogowi, spedytorzy, importerzy/eksporterzy,
a pośrednio — mieszkańcy miast portowych (mniej korków wokół portu).

---

## 3. Rozwiązanie — proces po wdrożeniu PulsePort

Ten sam proces, ale **predykcyjny i wspólny dla wszystkich stron**:

- **Kierowca** otwiera aplikację (mobilny HUD): widzi gigantyczny, jednoznaczny komunikat
  „JEDŹ TERAZ" lub „ZATOR — +22 min do bramy", status slotu, czas dojazdu i — jeśli trzeba —
  rekomendację zjazdu na parking buforowy. Zero rozpraszania, decyzja w 0,5 s.
- **Dyspozytor** ma „control tower": żywą mapę kongestii (TomTom), ranking wąskich gardeł,
  **predykcję narastania korków na 1–12 h naprzód (model ML)**, scoring ryzyka opóźnień
  z rozbiciem na składniki (ruch, anomalia, pogoda, presja portu, pora dnia), analitykę
  pogodową i automatyczne raporty operacyjne (LLM). Może wysłać powiadomienie push do kierowców.
- **Klient B2B** loguje się do portalu i widzi swoje kontenery: status trasy, postęp dostawy,
  ETA i ostrzeżenie o ryzyku kary — zanim ono wystąpi.

Wszystko spięte jednym backendem i jednym strumieniem danych odświeżanym automatycznie.

---

## 4. Dlaczego to jest innowacyjne

- **Fuzja danych zamiast pojedynczego źródła.** Łączymy komercyjne dane TomTom z **darmowymi,
  publicznymi systemami miejskimi** (TRISTAR Gdynia, ZDiTM Szczecin) oraz pogodą (Open-Meteo)
  i kontekstem portowym (awizacje statków). To daje sygnał, którego żadne pojedyncze źródło nie ma.
- **Predykcja, nie tylko monitoring.** Większość map ruchu pokazuje „teraz". My liczymy
  **Indeks Presji Zatorowej (CPI)** i prognozę ML (XGBoost) z rozbiciem na zrozumiałe składniki —
  dyspozytor wie *dlaczego* będzie korek, nie tylko *że* jest.
- **Jeden silnik — trzy persony.** Te same dane podane trzem rolom we właściwej formie
  (HUD dla kierowcy, control tower dla dyspozytora, portal śledzenia dla klienta) — to spaja
  proces, który dziś jest rozbity między telefon, e-mail i intuicję.
- **Skupienie na „ostatnim kilometrze" portu.** Drogi *wewnątrz* portu są prywatne; my celujemy
  dokładnie w przestrzeń, której nikt nie pokrywa: obwodnice i arterie dojazdowe do bram.
- **Wyjaśnialność i niski koszt.** Scoring i raporty są czytelne dla człowieka (LLM tworzy
  narrację, reguły liczą fakty), a architektura działa na darmowych/freemium źródłach.

---

## 5. Skalowalność i dopasowanie do rynku

PulsePort **nie jest zaszyty pod jeden port** — to konfiguracja, nie przepisywanie kodu.

- **Inne porty (ten sam sektor):** dodanie portu = wpis w `app/ports.py` (współrzędne bram
  i monitorowanych arterii). Architektura źródeł jest pluginowa — TomTom działa globalnie,
  a lokalne systemy ITS podpina się jako kolejny adapter (jak TRISTAR/ZDiTM).
- **Inne sektory (poza portami):** ten sam wzorzec — „przewiduj kongestię na dojeździe do
  węzła z oknami czasowymi" — pasuje do **centrów logistycznych i magazynów (sloty dokowe),
  lotnisk cargo, terminali kolejowych/intermodalnych, dużych zakładów produkcyjnych** (just-in-time),
  a nawet placów budowy zaopatrywanych „na slot".
- **Nisza → szerszy rynek:** rdzeń (fuzja danych o ruchu + predykcja + sloty + 3 persony)
  jest domenowo-agnostyczny. Zmienia się tylko warstwa źródeł i słownictwo widoków.
- **Niski próg wejścia:** opiera się na publicznych/freemium API, więc pilotaż w nowej
  lokalizacji jest tani i szybki.

---

## 6. Prezentacja rozwiązania — co działa, a co jest mockupem

Transparentnie rozdzielamy to, co działa na **realnych danych**, od **mockupów** (warstwa
demonstracyjna, gdzie brakuje jeszcze integracji z systemami biznesowymi — np. TOS terminala
czy systemem awizacji spedytora).

### ✅ Oparte o realne dane / działające

| Obszar | Status | Źródło |
| --- | --- | --- |
| Żywa mapa kongestii + incydenty | Realne | TomTom Traffic Flow / Incidents (kafelki + API) |
| Stan punktów (prędkość, kongestia, zamknięcia) | Realne | TomTom + TRISTAR (Gdynia) + ZDiTM (Szczecin) |
| Wąskie gardła, detekcja anomalii | Realne | Agregacja własna z historii SQLite |
| **Predykcja kongestii 1–12 h** | Realne | Model ML **XGBoost** (`/api/predictions`) |
| Scoring ryzyka opóźnień (5 składników) | Realne | Silnik CPI (`/api/risk-scores`) |
| Pogoda i jej wpływ na ruch | Realne | Open-Meteo (`/api/weather`) |
| Cechy czasowe (szczyt, weekend, święto) | Realne | Kalendarz + reguły |
| Raporty operacyjne (narracja) | Realne | Groq LLM + fallback regułowy |
| Eksport raportu do PDF | Realne | `fpdf2` |
| Powiadomienia push | Realne (pipeline) | Firebase Cloud Messaging\* |
| Strona tytułowa + routing 3 ról | Realne | FastAPI + SPA React (`/app`) |

\* Rejestracja tokenu i wysyłka działają; wysyłka wymaga prywatnego klucza serwisowego
Firebase (`firebase_credentials.json`) po stronie backendu.

### 🟡 Mockupy / warstwa demonstracyjna

| Obszar | Status | Uwaga |
| --- | --- | --- |
| **Portal Klienta B2B — tabela przesyłek i KPI** | Mock | Brak integracji z systemem awizacji/spedytora; dane (kontenery, ETA, demurrage) są przykładowe, na żywo tylko znacznik czasu pomiaru |
| **Widok Kierowcy — scenariusz alertu** | Tryb symulacji domyślnie | Przełącznik „dane na żywo" pokazuje realny stan z `/api/status`; symulacja służy do demonstracji krytycznego scenariusza |
| Strefa buforowa (liczba wolnych miejsc) | Mock | Brak źródła danych o zajętości parkingów buforowych |
| Przypisanie slotu / numeru bramy | Poglądowe | Wymaga integracji z systemem TOS terminala |
| Historia kongestii / wzorzec dobowy (wykresy) | Realne, ale rzadkie | Endpointy realne; baza zbiera dane od niedawna, więc wykresy wypełniają się z czasem |

### Czego jeszcze nie rozwiązaliśmy

- Integracji z systemami awizacji terminali (TOS) i spedytorów — to klucz do produkcyjnego
  Portalu Klienta i realnego przypisania slotów.
- Realnego źródła zajętości parkingów buforowych.
- Pełnej integracji harmonogramów statków (AIS) w scoringu (fundament istnieje).

---

## Architektura i stos technologiczny

- **Backend:** FastAPI (Python), SQLite, APScheduler (polling w tle), WebSocket (AIS).
- **Predykcja / analityka:** XGBoost + scikit-learn, własny silnik CPI, cechy czasowe.
- **LLM:** Groq (raporty operacyjne) z fallbackiem regułowym.
- **Frontend:**
  - **Strona tytułowa** (`landing.html`) + **dashboard dyspozytora** (Vanilla JS, Leaflet) — `app/static`.
  - **SPA React** (Vite + Tailwind + lucide) z widokami Kierowcy i Klienta — budowane do
    `app/static/spa`, serwowane przez FastAPI pod `/app`.
- **Powiadomienia:** Firebase Cloud Messaging (web push + service worker).
- **Eksport:** PDF (`fpdf2`).

### Źródła danych

| Źródło | Zakres | Rola |
| --- | --- | --- |
| TomTom Traffic API | Flow, Incidents, kafelki | Stan ruchu i mapa (globalnie) |
| TRISTAR (Gdynia) | Natężenie poj./h | Lokalny sygnał ITS |
| ZDiTM (Szczecin) | Prędkości GPS (proxy) | Lokalny sygnał ITS |
| Open-Meteo | Pogoda | Wpływ warunków na ruch |
| AIS / awizacje | Ruch statków | Presja portowa (w toku) |
| Groq | LLM | Narracja raportów |

---

## Uruchomienie

Wymagany **Python 3.10+** oraz **Node 18+** (do budowy SPA).

```bash
# 1) Backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2) Konfiguracja
cp .env.example .env             # ustaw TOMTOM_API_KEY oraz (opcjonalnie) GROQ_API_KEY

# 3) Budowa SPA (widoki Kierowcy/Klienta serwowane pod /app)
cd frontend && npm install && npm run build && cd ..

# 4) Start
uvicorn app.main:app --reload
```

Otwórz **http://localhost:8000** — strona tytułowa z wyborem roli:

- **Dyspozytor** → `/app#/dyspozytor` (control tower, dane na żywo)
- **Kierowca** → `/app#/kierowca` (mobilny HUD)
- **Klient B2B** → `/app#/klient` (portal śledzenia)
- Klasyczny dashboard (Vanilla, z powiadomieniami) pozostaje pod `/dyspozytor`.

Scheduler startuje z aplikacją i co `POLL_INTERVAL_SECONDS` odpytuje źródła. Predykcje
i wąskie gardła stają się sensowne po kilku-kilkunastu minutach zbierania danych.

> Dane ruchu wymagają ważnego klucza TomTom (plan freemium ma dzienne limity — dostosuj
> `POLL_INTERVAL_SECONDS`). Po każdej zmianie widoków React uruchom ponownie `npm run build`.

---

## Wybrane endpointy REST

| Metoda | Ścieżka | Opis |
| --- | --- | --- |
| GET | `/api/status` | Bieżący stan punktów (kongestia, prędkość) |
| GET | `/api/predictions?horizon=1` | Predykcja ML narastania korków (1–12 h) |
| GET | `/api/risk-scores` | Scoring ryzyka opóźnień (5 składników) |
| GET | `/api/bottlenecks?window=60` | Ranking wąskich gardeł |
| GET | `/api/weather` | Pogoda per port + wpływ na ruch |
| GET | `/api/analytics/congestion-history` | Historia kongestii (agregaty) |
| GET | `/api/analytics/daily-pattern` | Wzorzec dobowy punktu |
| GET | `/api/reports` · `POST /api/reports/on-demand` | Raporty operacyjne (LLM) |
| GET | `/api/reports/{point_id}/pdf` | Eksport raportu do PDF |
| POST | `/api/notifications/subscribe` | Rejestracja tokenu push |
| POST | `/api/refresh` | Wymuszenie pollingu |

## Metryka kongestii

`congestion_ratio = 1 − currentSpeed / freeFlowSpeed` (0 = płynnie, ~1 = stoi).
Zamknięcie drogi traktowane jako poziom krytyczny. Progi w `app/config.py`
(`warning ≥ 0.30`, `critical ≥ 0.55`).

## Struktura projektu

```
app/
  main.py            # FastAPI: REST + serwowanie frontu + start schedulera
  config.py          # klucze, progi, parametry pollingu
  ports.py           # definicje portów i monitorowanych punktów
  tomtom.py          # klient TomTom (Flow, Incidents, kafelki)
  tristar.py         # klient TRISTAR (Gdynia)
  zditm.py           # klient ZDiTM (Szczecin)
  analysis.py        # kongestia, wąskie gardła, anomalie, predykcja, scoring
  ml.py              # model XGBoost (predykcja kongestii)
  cpi.py             # Indeks Presji Zatorowej
  reports.py         # detekcja sytuacji + raporty (Groq + fallback)
  groq_client.py     # klient Groq (LLM)
  scheduler.py       # cykliczny polling (APScheduler)
  storage.py         # SQLite (pomiary, incydenty, pogoda, subskrypcje)
  static/            # landing.html, dashboard Vanilla (Leaflet), build SPA (/spa)
backend/services/
  notifications/     # Firebase Cloud Messaging (push)
  reports/           # generator PDF
frontend/            # SPA React (Vite + Tailwind): widoki ról
  src/features/{roles,dispatcher,driver,client-tracking}/
```

---

## Zespół

Projekt rozwijany przez 3-osobowy zespół (UI/role, raporty/powiadomienia,
analityka/predykcja/pogoda). Szczegółowy podział i roadmapa: `docs/plan-podzial-pracy-i-ulepszenia.md`.
