"""Dane portowe (Codeco + PortCalls + DspShips) i skladnik PresjaPortu dla CPI.

DANE HISTORYCZNE - wczytywane RAZ (lru_cache), nie w petli pollingu. Snapshot konczy
sie ~2026-06-23 13:03, dlatego "teraz" dla presji kotwiczymy domyslnie w najnowszym
znaczniku Codeco (reference_now). Brak live feedu terminali - presja odzwierciedla stan
snapshotu, nie biezacy strumien.

PresjaPortu(terminal, horizon_h) sklada sie z dwoch niezaleznych sygnalow w [0,1]:

  codeco  - anomalia tempa: zdarzenia w ostatniej godzinie / mediana dla tej samej
            (godzina, dzien_tygodnia) z ostatnich N tygodni. Powyzej typowej = presja.
            Dziala dla wszystkich 4 terminali (komplet danych).
  ships   - nadchodzaca fala ciezarowek: statki z ETA w oknie wyprzedzajacym, ich DWT
            rozsmarowane krzywa popytu (ciezarowki schodza przez kilka h PO cumowaniu).
            Realnie niezerowe glownie dla DCT/Gdansk - PortCalls przy snapshocie ma
            statki prawie wylacznie w Gdansku.

Zwracany total = clamp(codeco + ships, 0, 1); skladniki raportowane osobno wraz z
dominujacym statkiem (dominant_ship) - material dla narracji w reports.py.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .config import settings

DATA_DIR = Path(__file__).parent.parent / "data"

# Terminal kontenerowy -> monitorowany punkt (uzgodnione z uzytkownikiem, KROK D).
TERMINAL_POINT: Dict[str, str] = {
    "DCT": "gda_sucharskiego",   # Deepwater Container Terminal, Gdansk
    "BCT": "gdy_wisniewskiego",  # Baltic Container Terminal, Gdynia
    "GCT": "gdy_polska",         # Gdynia Container Terminal, Gdynia
    "DBPS": "szcz_gdanska",      # DB Port Szczecin, Szczecin
}
POINT_TERMINAL: Dict[str, str] = {v: k for k, v in TERMINAL_POINT.items()}

# Mapowanie miasta portu (PortCalls) -> terminal, gdy nabrzeze nie zawiera kodu terminala.
# Przy snapshocie statki sa praktycznie wylacznie w Gdansku -> DCT.
_PORT_CITY_TERMINAL = [
    ("gdansk", "DCT"),
    ("nowy port", "DCT"),
    ("gdynia", "BCT"),
    ("szczecin", "DBPS"),
]


# --- Wczytywanie danych (raz) -------------------------------------------------
@lru_cache(maxsize=1)
def _load_codeco() -> pd.DataFrame:
    frames = []
    for f in sorted(DATA_DIR.glob("Codeco*.xlsx")):
        df = pd.read_excel(f, header=1)
        frames.append(df)
    codeco = pd.concat(frames, ignore_index=True)
    codeco["terminal"] = codeco["Terminal rozładunkowy"].fillna(codeco["Terminal załadunkowy"])
    codeco["t"] = pd.to_datetime(codeco["Czas załadunku/wyładunku"], errors="coerce")
    codeco = codeco.dropna(subset=["t", "terminal"]).copy()
    codeco["hour"] = codeco["t"].dt.hour
    codeco["dow"] = codeco["t"].dt.dayofweek
    return codeco


@lru_cache(maxsize=1)
def _load_portcalls() -> pd.DataFrame:
    pc = pd.read_excel(DATA_DIR / list(p.name for p in DATA_DIR.glob("PortCalls*.xlsx"))[0], header=1)
    pc["eta"] = pd.to_datetime(pc["ETA"], errors="coerce")
    pc["dwt"] = pd.to_numeric(pc["DWT - nośność statku"], errors="coerce")
    pc["quay"] = pc["Nazwa nabrzeża"].astype(str)
    pc["port_city"] = pc["Nazwa portu"].astype(str).str.lower()
    pc["ship"] = pc["Nazwa statku"].astype(str)
    return pc.dropna(subset=["eta"]).copy()


@lru_cache(maxsize=1)
def reference_now() -> datetime:
    """Kotwica 'teraz' = najnowszy znacznik w Codeco (snapshot danych)."""
    return _load_codeco()["t"].max().to_pydatetime()


@lru_cache(maxsize=1)
def _baseline_table() -> Dict[Tuple[str, int, int], float]:
    """Mediana liczby zdarzen na (terminal, godzina, dzien_tygodnia) z N tygodni.

    Dla kazdego dnia liczymy zdarzenia w danej godzinie, potem mediana po dniach
    przypadajacych na ten sam dzien tygodnia - odporne na pojedyncze skoki.
    """
    codeco = _load_codeco()
    cutoff = reference_now() - timedelta(weeks=settings.pp_baseline_weeks)
    recent = codeco[codeco["t"] >= cutoff]
    # liczba zdarzen per (terminal, konkretny dzien, godzina)
    per_day = (
        recent.assign(date=recent["t"].dt.date)
        .groupby(["terminal", "dow", "date", "hour"])
        .size()
        .reset_index(name="n")
    )
    med = per_day.groupby(["terminal", "dow", "hour"])["n"].median()
    return {(t, int(d), int(h)): float(v) for (t, d, h), v in med.items()}


def _truck_kernel(hours_since_berth: float) -> float:
    """Krzywa popytu na ciezarowki po cumowaniu: 0 przed, narasta do szczytu, gasnie.

    Trojkatna: 0 w chwili cumowania -> 1 w pp_truck_peak_hours -> 0 w pp_truck_spread_hours.
    """
    peak = settings.pp_truck_peak_hours
    end = settings.pp_truck_spread_hours
    if hours_since_berth < 0 or hours_since_berth >= end:
        return 0.0
    if hours_since_berth <= peak:
        return hours_since_berth / peak if peak > 0 else 1.0
    return max(0.0, (end - hours_since_berth) / (end - peak))


def _ship_terminal(row: pd.Series) -> Optional[str]:
    """Terminal statku: najpierw z nazwy nabrzeza (kod), potem z miasta portu."""
    quay = str(row["quay"]).upper()
    for term in TERMINAL_POINT:
        if term in quay:
            return term
    city = str(row["port_city"]).lower()
    for needle, term in _PORT_CITY_TERMINAL:
        if needle in city:
            return term
    return None


# --- PresjaPortu --------------------------------------------------------------
def compute_port_pressure(
    terminal: str, horizon_h: float, now: Optional[datetime] = None
) -> Dict[str, Any]:
    """Rozlozona presja portu dla terminala na horyzont horizon_h (godziny).

    Zwraca: codeco, ships (skladniki [0,1]), total, codeco_ratio, dominant_ship,
    ships_in_window. Brak danych -> skladnik 0.
    """
    now = now or reference_now()
    result: Dict[str, Any] = {
        "terminal": terminal,
        "horizon_h": horizon_h,
        "codeco": 0.0,
        "ships": 0.0,
        "total": 0.0,
        "codeco_ratio": None,
        "dominant_ship": None,
        "ships_in_window": 0,
    }
    if terminal not in TERMINAL_POINT:
        return result

    # --- skladnik Codeco: anomalia tempa w ostatniej godzinie vs baseline ---
    codeco = _load_codeco()
    last_h = codeco[
        (codeco["terminal"] == terminal)
        & (codeco["t"] > now - timedelta(hours=1))
        & (codeco["t"] <= now)
    ]
    current_rate = float(len(last_h))
    baseline = _baseline_table().get((terminal, now.weekday(), now.hour))
    if baseline and baseline > 0:
        ratio = current_rate / baseline
        result["codeco_ratio"] = round(ratio, 2)
        full = settings.pp_codeco_full_ratio  # ratio=full -> skladnik 1.0 (ponad typowa)
        result["codeco"] = max(0.0, min(1.0, (ratio - 1.0) / (full - 1.0))) if full > 1 else 0.0

    # --- skladnik statkow: DWT z ETA w oknie, rozsmarowane krzywa popytu ---
    target = now + timedelta(hours=horizon_h)
    pc = _load_portcalls()
    window = pc[(pc["eta"] >= now) & (pc["eta"] <= target + timedelta(hours=4))].copy()
    weighted_dwt = 0.0
    best: Optional[Tuple[float, str, float]] = None  # (wklad, statek, dwt)
    count = 0
    for _, row in window.iterrows():
        if _ship_terminal(row) != terminal:
            continue
        dwt = float(row["dwt"]) if pd.notna(row["dwt"]) else 0.0
        hours_since_berth = (target - row["eta"].to_pydatetime()).total_seconds() / 3600.0
        w = _truck_kernel(hours_since_berth)
        contrib = dwt * w
        count += 1
        weighted_dwt += contrib
        if w > 0 and (best is None or contrib > best[0]):
            best = (contrib, row["ship"], dwt)
    result["ships_in_window"] = count
    if settings.pp_ship_dwt_full > 0:
        result["ships"] = max(0.0, min(1.0, weighted_dwt / settings.pp_ship_dwt_full))
    if best is not None and best[0] > 0:
        result["dominant_ship"] = {"name": best[1], "dwt": best[2]}

    result["codeco"] = round(result["codeco"], 3)
    result["ships"] = round(result["ships"], 3)
    result["total"] = round(min(1.0, result["codeco"] + result["ships"]), 3)
    return result


def port_pressure_for_point(
    point_id: str, horizon_h: float, now: Optional[datetime] = None
) -> Dict[str, Any]:
    """PresjaPortu dla monitorowanego punktu (mapuje punkt->terminal). Bez terminala -> 0."""
    terminal = POINT_TERMINAL.get(point_id)
    if terminal is None:
        return {
            "terminal": None, "horizon_h": horizon_h, "codeco": 0.0, "ships": 0.0,
            "total": 0.0, "codeco_ratio": None, "dominant_ship": None, "ships_in_window": 0,
        }
    return compute_port_pressure(terminal, horizon_h, now)
