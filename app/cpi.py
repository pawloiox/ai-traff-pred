"""CPI - Indeks Presji Zatorowej: addytywny, interpretowalny model prognozy zatoru.

Dla punktu i horyzontu h (godziny) zwraca jedna liczbe [0,1] ORAZ jej rozklad na
cztery niezalezne skladniki - to serce projektu, bo rozklad jest materialem dla raportu:

  CPI(point, h) = w1*Baseline + w2*Trend + w3*PortPressure + w4*Incidents

  Baseline      - typowy poziom kongestii w punkcie dla PRZYSZLEJ (godzina, dzien_tyg)
                  z historii TomTom; fallback na zimno gdy brak historii.
  Trend         - biezaca dynamika z regresji ostatnich pomiarow, wplyw SLABNIE z h.
  PortPressure  - presja portu (Codeco baseline + zywe statki) z portdata.
  Incidents     - incydenty TomTom w promieniu punktu.

Skladnik bez danych (np. za malo historii na Trend) jest pomijany, a wagi
renormalizowane po dostepnych - CPI nie jest wtedy sztucznie zanizony.
confidence = najslabsze ogniwo wsrod skladnikow, ktore realnie waza.
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from . import portdata
from .config import settings
from .ports import get_point
from .storage import storage

# Ranking jakosci danych do "najslabszego ogniwa".
_QUALITY_RANK = {"measured": 3, "proxy": 2, "predicted": 1}
_EPS = 1e-6


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    p = math.pi / 180.0
    a = (
        0.5
        - math.cos((lat2 - lat1) * p) / 2
        + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2
    )
    return 2 * R * math.asin(math.sqrt(a))


def _baseline(point_id: str, target: datetime) -> Tuple[Optional[float], str]:
    """Typowy congestion_ratio dla (dzien_tyg, godzina) docelowego czasu, z historii TomTom.

    Zwraca (wartosc, jakosc). 'measured' gdy jest kubelek czasowy, 'predicted' gdy
    fallback na ogolna mediane punktu, (None, '') gdy brak jakiejkolwiek historii.
    """
    since = time.time() - settings.measurement_retention_seconds
    rows = storage.measurements_since(since, point_id=point_id, source="tomtom")
    ratios_all: List[float] = []
    ratios_bucket: List[float] = []
    for r in rows:
        ratio = r.get("congestion_ratio")
        if ratio is None:
            continue
        ratios_all.append(ratio)
        dt = datetime.fromtimestamp(r["ts"])
        if dt.weekday() == target.weekday() and dt.hour == target.hour:
            ratios_bucket.append(ratio)
    if ratios_bucket:
        return float(np.median(ratios_bucket)), "measured"
    if ratios_all:
        return float(np.median(ratios_all)), "predicted"  # brak kubelka -> mniej pewne
    return None, ""


def _trend(point_id: str, horizon_h: float, now: datetime) -> Tuple[Optional[float], str]:
    """Projekcja kongestii z nachylenia ostatnich pomiarow; wplyw nachylenia slabnie z h.

    proj = clamp(current + slope*h*exp(-h/tau)). Zwraca (wartosc, 'measured') lub
    (None,'') gdy za malo probek.
    """
    window_s = settings.cpi_trend_window_minutes * 60
    rows = storage.measurements_since(time.time() - window_s, point_id=point_id, source="tomtom")
    series = [(r["ts"], r["congestion_ratio"]) for r in rows if r.get("congestion_ratio") is not None]
    if len(series) < 3:
        return None, ""
    ts = np.array([s[0] for s in series], dtype=float)
    ratios = np.array([s[1] for s in series], dtype=float)
    t_h = (ts - ts[0]) / 3600.0  # czas w godzinach
    slope, _ = np.polyfit(t_h, ratios, 1)  # ratio na godzine
    current = float(ratios[-1])
    decay = math.exp(-horizon_h / settings.cpi_trend_tau_h)
    proj = current + float(slope) * horizon_h * decay
    return max(0.0, min(1.0, proj)), "measured"


def _incidents(point_id: str) -> Tuple[float, str]:
    """Sygnal incydentow [0,1] z TomTom w promieniu punktu (max magnitude/4)."""
    resolved = get_point(point_id)
    if resolved is None:
        return 0.0, "measured"
    port, point = resolved
    score = 0.0
    for inc in storage.current_incidents(port.id):
        lat, lon = inc.get("lat"), inc.get("lon")
        if lat is None or lon is None:
            continue
        if _haversine_m(point.lat, point.lon, lat, lon) <= settings.incident_link_radius_m:
            mag = inc.get("magnitude") or 0
            score = max(score, min(1.0, mag / 4.0))
    return score, "measured"


def compute_cpi(point_id: str, horizon_h: float, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Rozlozony CPI dla punktu na horyzont horizon_h (godziny)."""
    now = now or datetime.now(timezone.utc)
    target = now + timedelta(hours=horizon_h)

    b_val, b_q = _baseline(point_id, target.astimezone())
    t_val, t_q = _trend(point_id, horizon_h, now)
    pp = portdata.port_pressure_for_point(point_id, horizon_h)
    inc_val, inc_q = _incidents(point_id)

    # PortPressure jest forward-looking -> 'predicted'. Zawsze dostepny (0 bez terminala).
    pp_val = pp["total"]
    pp_q = "predicted"

    # (wartosc, waga, jakosc, dostepnosc)
    comps = {
        "baseline": (b_val, settings.cpi_w_baseline, b_q),
        "trend": (t_val, settings.cpi_w_trend, t_q),
        "port_pressure": (pp_val, settings.cpi_w_port_pressure, pp_q),
        "incidents": (inc_val, settings.cpi_w_incidents, inc_q),
    }
    available = {k: v for k, v in comps.items() if v[0] is not None}
    total_w = sum(w for (_, w, _) in available.values()) or 1.0

    total = 0.0
    contributions: Dict[str, float] = {}
    eff_weights: Dict[str, float] = {}
    for name, (val, w, _q) in available.items():
        ew = w / total_w
        eff_weights[name] = round(ew, 3)
        contributions[name] = val * ew
        total += val * ew

    dominant = max(contributions, key=contributions.get) if contributions else None

    # confidence = najslabsze ogniwo wsrod skladnikow, ktore realnie waza (wklad > 0).
    contributing = [(name, comps[name][2]) for name in available if contributions[name] > _EPS]
    if contributing:
        weakest = min(contributing, key=lambda c: _QUALITY_RANK.get(c[1], 1))
        confidence = weakest[1]
    else:
        confidence = "measured"

    return {
        "point_id": point_id,
        "horizon_h": horizon_h,
        "total": round(min(1.0, max(0.0, total)), 3),
        "baseline": round(b_val, 3) if b_val is not None else None,
        "trend": round(t_val, 3) if t_val is not None else None,
        "port_pressure": round(pp_val, 3),
        "incidents": round(inc_val, 3),
        "weights": eff_weights,
        "dominant_component": dominant,
        "confidence": confidence,
        "port_pressure_detail": {
            "codeco": pp["codeco"],
            "ships": pp["ships"],
            "dominant_ship": pp["dominant_ship"],
            "codeco_ratio": pp["codeco_ratio"],
        },
    }
