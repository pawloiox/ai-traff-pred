# Port Traffic Pulse

Zywy uklad nerwowy portu - narzedzie czasu rzeczywistego do wizualizacji ruchu drogowego
na drogach dojazdowych do terminali portowych w **Gdansku, Gdyni i Szczecinie-Swinoujsciu**.

Wersja pierwotna (MVP) oparta o **TomTom Traffic API** (Traffic, Traffic Flow, Traffic Incidents).

## Co potrafi

- **Zywa mapa kongestii** - mapa Leaflet z kafelkami TomTom (baza, Traffic Flow, Traffic Incidents)
  oraz markerami monitorowanych punktow kolorowanymi wg poziomu zatoru.
- **Waskie gardla z ostatniej godziny** - ranking punktow wg sredniej kongestii.
- **Raporty operacyjne (Groq / LLM)** - narracja raportu generowana przez model Groq
  na podstawie ustrukturyzowanych danych (stan, przyczyna, rekomendacja, trend), z korelacja
  incydentow TomTom. Przy bledzie/niedostepnosci Groq dziala fallback regulowy.
- **Detekcja anomalii** - z-score biezacej kongestii wzgledem baseline punktu.
- **Predykcja narastania korkow** - regresja liniowa trendu z ostatnich ~30 min i prognoza.

## Zrodlo danych: TomTom

| Funkcja | Endpoint |
| --- | --- |
| Punktowy stan drogi (Traffic Flow) | `GET /traffic/services/4/flowSegmentData/absolute/10/json` |
| Incydenty (Traffic Incidents v5) | `GET /traffic/services/5/incidentDetails` |
| Kafelki bazowej mapy | `/map/1/tile/basic/main/{z}/{x}/{y}.png` |
| Kafelki Traffic Flow | `/traffic/map/4/tile/flow/relative0/{z}/{x}/{y}.png` |
| Kafelki Traffic Incidents | `/traffic/map/4/tile/incidents/s3/{z}/{x}/{y}.png` |

Drogi wewnatrz portow sa zwykle prywatne i poza danymi miejskimi/TomTom - monitorujemy
obwodnice i glowne trasy dojazdowe (np. Trasa Sucharskiego, ul. Marynarki Polskiej,
Estakada Kwiatkowskiego).

## Instalacja

Wymagany Python 3.10+.

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Linux/macOS:
# source .venv/bin/activate

pip install -r requirements.txt
```

## Konfiguracja

Skopiuj `.env.example` do `.env` i ustaw klucze (domyslnie uzyte sa klucze z zadania):

```
TOMTOM_API_KEY=twoj_klucz
POLL_INTERVAL_SECONDS=60
DB_PATH=traffic.db
GROQ_API_KEY=twoj_klucz_groq
GROQ_MODEL=llama-3.1-8b-instant
GROQ_ENABLED=true
```

### Raporty operacyjne przez Groq

Raporty sa generowane przez model Groq raz na cykl pollingu (`POLL_INTERVAL_SECONDS`)
i buforowane - endpoint `GET /api/reports` zwraca gotowe wyniki bez wywolywania LLM,
co oszczedza limity zapytan. Detekcja sytuacji (waskie gardla, anomalie, predykcje,
pobliskie incydenty) pozostaje regulowa; Groq tworzy tylko tresc raportu (`headline`,
`cause`, `recommendation`, `summary`). Pole `source` w raporcie wskazuje `groq` lub `rule`
(fallback). Ustaw `GROQ_ENABLED=false`, aby korzystac wylacznie z raportow regulowych.

Oszczedzanie darmowego limitu Groq:

- domyslny model to `llama-3.1-8b-instant` (14.4k zapytan/dobe, 500k tokenow/dobe) -
  zadanie jest proste (krotki JSON oparty na policzonych danych), a modele 70B/120B
  maja tylko 1k zapytan/dobe i przy generacji co minute szybko zwracaja `429`;
- wszystkie zmienione sytuacje ida w JEDNYM zbiorczym zapytaniu na cykl (zamiast po
  jednym na punkt), co tnie liczbe zapytan nawet kilkukrotnie;
- narracje stabilnych sytuacji sa reuzywane z cache (Groq wolany tylko gdy stan punktu
  realnie sie zmieni), wiec w spokojnym ruchu liczba zapytan spada niemal do zera.

## Uruchomienie

```bash
uvicorn app.main:app --reload
```

Mapa: http://localhost:8000

Scheduler startuje razem z aplikacja i co `POLL_INTERVAL_SECONDS` odpytuje TomTom.
Waskie gardla i predykcje staja sie sensowne po kilku-kilkunastu minutach zbierania danych.

## Endpointy REST

| Metoda | Sciezka | Opis |
| --- | --- | --- |
| GET | `/api/ports` | Lista portow, punktow i URL-e kafelkow TomTom |
| GET | `/api/status` | Biezacy stan wszystkich punktow (kongestia, predkosc) |
| GET | `/api/bottlenecks?window=60&limit=10` | Ranking waskich gardel z okna czasu |
| GET | `/api/incidents?port=gdansk` | Aktywne incydenty (opcjonalnie per port) |
| GET | `/api/anomalies` | Wykryte anomalie kongestii |
| GET | `/api/predictions` | Prognozy narastania korkow |
| GET | `/api/reports?limit=8` | Wygenerowane raporty operacyjne |
| POST | `/api/refresh` | Wymusza natychmiastowy polling TomTom |

## Struktura projektu

```
app/
  config.py      # klucz TomTom, progi, parametry pollingu
  ports.py       # definicje portow i monitorowanych punktow
  tomtom.py      # klient TomTom: Flow, Incidents, URL kafelkow
  groq_client.py # klient Groq (LLM) - narracja raportow
  storage.py     # SQLite (measurements, incidents)
  scheduler.py   # cykliczny polling (APScheduler) + odswiezanie raportow
  analysis.py    # kongestia, bottlenecks, anomalie, predykcja
  reports.py     # detekcja sytuacji + raporty (Groq z fallbackiem) + bufor
  main.py        # FastAPI: REST + front + start schedulera
  static/        # mapa Leaflet (index.html, app.js, styles.css)
```

## Metryka kongestii

`congestion_ratio = 1 - currentSpeed / freeFlowSpeed` (0 = plynnie, ~1 = stoi).
Zamkniecie drogi (`roadClosure`) traktowane jest jako poziom krytyczny (1.0).

Progi (konfigurowalne w `app/config.py`): `warning >= 0.30`, `critical >= 0.55`.

## Uwagi

- Wspolrzedne punktow w `app/ports.py` to wartosci startowe do kalibracji na mapie.
- Predykcja jest lekka (trend liniowy + baseline), bez ciezkiego ML - zgodnie z zalozeniem MVP.
- TomTom plan freemium ma dzienne limity zapytan; dostosuj `POLL_INTERVAL_SECONDS`.