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
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from . import portcalls_live
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

    # --- skladnik statkow: zywe ETA z UM Gdynia, rozsmarowane krzywa popytu ---
    # Statki sa LIVE -> 'teraz' to zegar biezacy (tz-aware), nie snapshot Codeco.
    ship_now = datetime.now(timezone.utc)
    target = ship_now + timedelta(hours=horizon_h)
    window_end = target + timedelta(hours=4)
    weighted_dwt = 0.0
    best: Optional[Tuple[float, str, float]] = None  # (wklad, statek, dwt)
    count = 0
    for ship in portcalls_live.get_cached_ships():
        terminals = ship.get("terminals") or []
        if terminal not in terminals:
            continue
        eta = ship.get("eta")
        if eta is None or not (ship_now <= eta <= window_end):
            continue
        count += 1
        dwt = float(ship["dwt"]) if ship.get("dwt") else 0.0
        if dwt <= 0:
            continue
        split = 1.0 / len(terminals)  # statek Gdyni dzielony 0.5 na BCT/GCT
        factor = portcalls_live.truck_factor(ship.get("ship_type"))
        hours_since_berth = (target - eta).total_seconds() / 3600.0
        w = _truck_kernel(hours_since_berth)
        contrib = dwt * factor * split * w
        weighted_dwt += contrib
        if w > 0 and (best is None or contrib > best[0]):
            best = (contrib, ship["ship"], dwt)
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
