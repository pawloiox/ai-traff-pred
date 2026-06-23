"""Generator raportow operacyjnych.

Detekcja sytuacji utrudnien (zator/narastanie/anomalia/incydent) jest regulowa,
a narracja raportu generowana jest przez Groq (LLM). Przy bledzie/niedostepnosci
Groq stosowany jest fallback regulowy. Wyniki sa buforowane w cyklu pollingu.
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from . import analysis, groq_client
from .config import settings
from .storage import storage

# Bufor raportow odswiezany w cyklu pollingu.
_cache: Dict[str, Any] = {"ts": None, "reports": []}

_SEVERITY = {"critical": 3, "warning": 2, "ok": 1, "unknown": 0}


def _haversine_m(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """Odleglosc w metrach miedzy (lat, lon)."""
    r = 6371000.0
    lat1, lon1, lat2, lon2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _nearest_incident(
    port_id: str, lat: Optional[float], lon: Optional[float]
) -> Optional[Dict[str, Any]]:
    if lat is None or lon is None:
        return None
    incidents = storage.current_incidents(port_id)
    best: Optional[Dict[str, Any]] = None
    best_dist = settings.incident_link_radius_m
    for inc in incidents:
        if inc.get("lat") is None or inc.get("lon") is None:
            continue
        dist = _haversine_m((lat, lon), (inc["lat"], inc["lon"]))
        if dist <= best_dist:
            best_dist = dist
            best = {**inc, "distance_m": round(dist)}
    return best


def _build_situations(limit: int = 20) -> List[Dict[str, Any]]:
    """Regulowa detekcja sytuacji wymagajacych raportu (bez narracji)."""
    bottleneck_list = analysis.bottlenecks(limit=limit)
    predictions = {p["point_id"]: p for p in analysis.predict_trends()}
    anomalies = {a["point_id"]: a for a in analysis.detect_anomalies()}

    situations: List[Dict[str, Any]] = []
    for b in bottleneck_list:
        pid = b["point_id"]
        pred = predictions.get(pid)
        anomaly = anomalies.get(pid)
        rising = bool(pred and pred["rising"])
        level = b["level"]

        # Raportujemy istotne sytuacje: zator, narastanie lub anomalia.
        if level == "ok" and not rising and not anomaly:
            continue

        incident = _nearest_incident(b["port_id"], b.get("lat"), b.get("lon"))
        situations.append(
            {
                "point_id": pid,
                "point_name": b["point_name"],
                "port_id": b["port_id"],
                "road": b.get("road"),
                "level": level,
                "rising": rising,
                "is_anomaly": anomaly is not None,
                "road_closure": b.get("closures", 0) > 0,
                "avg_ratio": b["avg_ratio"],
                "max_ratio": b["max_ratio"],
                "linked_incident": incident,
                "prediction": pred,
            }
        )

    situations.sort(
        key=lambda s: (_SEVERITY.get(s["level"], 0), s["rising"], s["avg_ratio"]),
        reverse=True,
    )
    return situations


# --- Fallback regulowy ------------------------------------------------------
def _cause_text(situation: Dict[str, Any]) -> str:
    incident = situation.get("linked_incident")
    if incident:
        label = incident.get("category_label") or "zdarzenie drogowe"
        desc = incident.get("description") or ""
        delay = incident.get("delay_seconds")
        delay_txt = f", opoznienie ok. {round(delay / 60)} min" if delay else ""
        detail = f" ({desc})" if desc and desc != "Brak opisu" else ""
        return f"{label}{detail} w odleglosci {incident['distance_m']} m{delay_txt}"
    return "brak zgloszonego incydentu - prawdopodobnie ruch godziny szczytu / natezenie pojazdow"


def _recommendation(situation: Dict[str, Any], has_incident: bool) -> str:
    road = situation.get("road") or situation["point_name"]
    if situation.get("level") == "critical" or situation.get("road_closure"):
        base = (
            f"wstrzymaj/rozloz w czasie wyjazdy ciezarowek przez {road}; "
            "rozwaz przekierowanie na trasy alternatywne i poinformuj brame terminala"
        )
    else:
        base = (
            f"monitoruj {road}, przygotuj bufor czasowy dla slotow bramowych; "
            "rozwaz wczesniejsze awizacje"
        )
    if has_incident:
        base += "; skoordynuj sie z zarzadca ruchu miasta w sprawie incydentu"
    return base


def _rule_based_narrative(situation: Dict[str, Any]) -> Dict[str, str]:
    level = situation["level"]
    rising = situation["rising"]
    name = situation["point_name"]

    if level == "critical":
        headline = f"Silny zator na {name}"
    elif rising:
        headline = f"Korek narasta na {name}"
    elif situation["is_anomaly"]:
        headline = f"Nietypowa kongestia na {name}"
    else:
        headline = f"Zwolniony ruch na {name}"

    cause = _cause_text(situation)
    recommendation = _recommendation(situation, situation.get("linked_incident") is not None)

    pred = situation.get("prediction")
    trend_txt = ""
    if pred:
        arrow = "rosnaca" if pred["rising"] else "stabilna/malejaca"
        trend_txt = (
            f" Tendencja {arrow}; prognoza na {pred['horizon_minutes']} min: "
            f"{round(pred['predicted_ratio'] * 100)}% kongestii."
        )

    summary = (
        f"{headline} ({round(situation['avg_ratio'] * 100)}% sredniej kongestii w ostatniej godzinie, "
        f"max {round(situation['max_ratio'] * 100)}%). "
        f"Prawdopodobna przyczyna: {cause}. "
        f"Rekomendacja: {recommendation}.{trend_txt}"
    )
    return {
        "headline": headline,
        "cause": cause,
        "recommendation": recommendation,
        "summary": summary,
    }


def _assemble(situation: Dict[str, Any], narrative: Dict[str, str], source: str, ts: float) -> Dict[str, Any]:
    return {
        "ts": ts,
        "point_id": situation["point_id"],
        "point_name": situation["point_name"],
        "port_id": situation["port_id"],
        "road": situation.get("road"),
        "level": situation["level"],
        "rising": situation["rising"],
        "is_anomaly": situation["is_anomaly"],
        "avg_ratio": situation["avg_ratio"],
        "max_ratio": situation["max_ratio"],
        "headline": narrative.get("headline") or "",
        "cause": narrative.get("cause") or "",
        "recommendation": narrative.get("recommendation") or "",
        "linked_incident": situation.get("linked_incident"),
        "prediction": situation.get("prediction"),
        "summary": narrative.get("summary") or "",
        "source": source,
    }


async def refresh_reports(limit: int = 8) -> List[Dict[str, Any]]:
    """Buduje sytuacje, generuje narracje przez Groq (z fallbackiem) i buforuje."""
    ts = time.time()
    situations = _build_situations(limit=20)[:limit]

    reports: List[Dict[str, Any]] = []
    if situations and settings.groq_enabled and settings.groq_api_key:
        async with httpx.AsyncClient(timeout=settings.groq_timeout) as client:
            results = await asyncio.gather(
                *(groq_client.generate_report(s, client=client) for s in situations)
            )
    else:
        results = [None] * len(situations)

    for situation, narrative in zip(situations, results):
        if narrative and (narrative.get("summary") or narrative.get("headline")):
            reports.append(_assemble(situation, narrative, "groq", ts))
        else:
            reports.append(_assemble(situation, _rule_based_narrative(situation), "rule", ts))

    _cache["ts"] = ts
    _cache["reports"] = reports
    return reports


def get_cached_reports(limit: int = 8) -> List[Dict[str, Any]]:
    return list(_cache.get("reports") or [])[:limit]


def cache_timestamp() -> Optional[float]:
    return _cache.get("ts")
