"""Generator raportow operacyjnych.

Detekcja sytuacji utrudnien (zator/narastanie/anomalia/incydent) jest regulowa,
a narracja raportu generowana jest przez Groq (LLM). Przy bledzie/niedostepnosci
Groq stosowany jest fallback regulowy. Wyniki sa buforowane w cyklu pollingu.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from . import analysis, cpi, groq_client
from .config import settings
from .storage import storage

# Horyzont (h), na ktory liczymy CPI dla narracji raportu (forward-looking przyczyna).
_CPI_REPORT_HORIZON_H = 2.0

# Bufor raportow odswiezany w cyklu pollingu.
_cache: Dict[str, Any] = {"ts": None, "reports": []}

# Cache narracji LLM wg sygnatury sytuacji - Groq wolany tylko przy zmianie.
# Klucz: sygnatura sytuacji -> {"narrative": {...}, "source": "groq"}.
_narrative_cache: Dict[str, Dict[str, Any]] = {}

# Słownik do unikania spamu push dla tego samego punktu (cooldown 30 minut)
_last_pushed_state: Dict[str, float] = {}

_SEVERITY = {"critical": 3, "warning": 2, "ok": 1, "unknown": 0}


def _situation_signature(s: Dict[str, Any]) -> str:
    """Stabilny podpis sytuacji - zmienia sie tylko przy istotnej zmianie stanu."""
    inc = s.get("linked_incident") or {}
    cpi_s = s.get("cpi") or {}
    ship = (cpi_s.get("port_pressure_detail") or {}).get("dominant_ship") or {}
    w_data = s.get("weather") or {}
    t_data = s.get("temporal") or {}
    parts = [
        str(s.get("point_id")),
        str(s.get("level")),
        "r1" if s.get("rising") else "r0",
        "a1" if s.get("is_anomaly") else "a0",
        "c1" if s.get("road_closure") else "c0",
        f"{round((s.get('avg_ratio') or 0), 2)}",
        f"{round((s.get('max_ratio') or 0), 2)}",
        str(inc.get("incident_id") or "-"),
        str(cpi_s.get("dominant_component") or "-"),
        str(ship.get("name") or "-"),
        "w1" if w_data.get("is_raining") else "w0",
        "t1" if t_data.get("is_rush_hour") else "t0"
    ]
    return "|".join(parts)


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
        try:
            cpi_result = cpi.compute_cpi(pid, _CPI_REPORT_HORIZON_H)
        except Exception:  # noqa: BLE001 - raport nie moze sie wywrocic przez blad CPI
            cpi_result = None
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
                "cpi": cpi_result,
            }
        )

    situations.sort(
        key=lambda s: (_SEVERITY.get(s["level"], 0), s["rising"], s["avg_ratio"]),
        reverse=True,
    )
    return situations


# --- Fallback regulowy ------------------------------------------------------
def _incident_text(incident: Dict[str, Any]) -> str:
    label = incident.get("category_label") or "zdarzenie drogowe"
    desc = incident.get("description") or ""
    delay = incident.get("delay_seconds")
    delay_txt = f", opoznienie ok. {round(delay / 60)} min" if delay else ""
    detail = f" ({desc})" if desc and desc != "Brak opisu" else ""
    return f"{label}{detail} w odleglosci {incident['distance_m']} m{delay_txt}"


def _cause_text(situation: Dict[str, Any]) -> str:
    """Przyczyna wg dominujacego skladnika CPI; incydent ma pierwszenstwo gdy istnieje."""
    incident = situation.get("linked_incident")
    cpi_s = situation.get("cpi") or {}
    dom = cpi_s.get("dominant_component")
    ship = (cpi_s.get("port_pressure_detail") or {}).get("dominant_ship") or {}

    weather_info = ""
    w_data = situation.get("weather")
    if w_data and w_data.get("is_raining"):
        weather_info = " Ponadto: niekorzystne warunki atmosferyczne (opady deszczu) dodatkowo pogarszają warunki drogowe."
        
    temporal_info = ""
    t_data = situation.get("temporal")
    if t_data and t_data.get("is_rush_hour"):
        temporal_info = " Ponadto: trwa okres szczytowego natężenia ruchu."

    base_cause = "Nie odnotowano zgłoszonych incydentów drogowych — utrudnienia wynikają z naturalnego natężenia ruchu w bieżącym okresie."
    if dom == "port_pressure" and ship.get("name"):
        base_cause = (
            f"Dominujący czynnik: presja ruchu portowego. Statek {ship['name']} (DWT {round(ship['dwt'])}) "
            f"zbliża się do cumowania, co generuje zwiększony ruch ciężarówek z terminala."
        )
    elif incident:
        base_cause = _incident_text(incident)
    elif dom == "trend":
        base_cause = "Dominujący czynnik: narastająca dynamika ruchu drogowego (trend wzrostowy odnotowany w ostatnich pomiarach)."
    elif dom == "baseline":
        base_cause = "Dominujący czynnik: typowe natężenie ruchu charakterystyczne dla bieżącej pory dnia i dnia tygodnia."

    return base_cause + weather_info + temporal_info


def _recommendation(situation: Dict[str, Any], has_incident: bool) -> str:
    road = situation.get("road") or situation["point_name"]
    if situation.get("level") == "critical" or situation.get("road_closure"):
        base = (
            f"Zaleca się wstrzymanie lub rozłożenie w czasie wyjazdów ciężarówek przez {road}. "
            "Należy rozważyć przekierowanie na trasy alternatywne oraz poinformować bramę terminala o utrudnieniach."
        )
    else:
        base = (
            f"Zaleca się bieżące monitorowanie sytuacji na {road} oraz przygotowanie buforu czasowego dla slotów bramowych. "
            "Rekomendowane jest rozważenie wcześniejszych awizacji."
        )
    if has_incident:
        base += " Dodatkowo zaleca się koordynację z zarządcą ruchu miejskiego w sprawie zgłoszonego incydentu."
    return base


def _driver_action(situation: Dict[str, Any]) -> str:
    """Generuje wniosek końcowy co do działania kierowców ciężarówek."""
    level = situation["level"]
    rising = situation["rising"]
    road = situation.get("road") or situation["point_name"]
    has_closure = situation.get("road_closure")

    if has_closure:
        return (
            f"WNIOSEK: Droga {road} jest zamknięta. Kierowcy ciężarówek powinni bezwzględnie "
            "wstrzymać wyjazdy na ten odcinek i skorzystać z wyznaczonych tras alternatywnych. "
            "Przed ponownym wyjazdem należy potwierdzić otwarcie trasy z dyspozytorem."
        )
    if level == "critical":
        return (
            f"WNIOSEK: Na odcinku {road} występuje silny zator. Kierowcy ciężarówek powinni "
            "wstrzymać planowane wyjazdy do czasu ustabilizowania się sytuacji drogowej. "
            "W przypadku konieczności przejazdu, zalecane jest skorzystanie z tras alternatywnych."
        )
    if level == "warning" and rising:
        return (
            f"WNIOSEK: Na odcinku {road} odnotowano narastające utrudnienia. Kierowcy ciężarówek "
            "powinni zachować wzmożoną ostrożność i uwzględnić dodatkowy czas przejazdu. "
            "Rekomendowane jest śledzenie bieżących komunikatów dyspozytorskich."
        )
    if level == "warning":
        return (
            f"WNIOSEK: Na odcinku {road} występuje umiarkowane zwolnienie ruchu. Kierowcy ciężarówek "
            "mogą kontynuować planowane przejazdy z zachowaniem ostrożności. "
            "Zalecane jest uwzględnienie dodatkowego buforu czasowego."
        )
    if situation.get("is_anomaly"):
        return (
            f"WNIOSEK: Na odcinku {road} wykryto nietypowe natężenie ruchu. Kierowcy ciężarówek "
            "powinni zachować ostrożność i być przygotowani na ewentualne opóźnienia."
        )
    return (
        f"WNIOSEK: Sytuacja na odcinku {road} nie wymaga szczególnych działań. "
        "Kierowcy ciężarówek mogą kontynuować planowane przejazdy zgodnie z harmonogramem."
    )


def _rule_based_narrative(situation: Dict[str, Any]) -> Dict[str, str]:
    level = situation["level"]
    rising = situation["rising"]
    name = situation["point_name"]

    if level == "critical":
        headline = f"Silny zator na {name}"
    elif rising:
        headline = f"Narastające utrudnienia — {name}"
    elif situation["is_anomaly"]:
        headline = f"Nietypowa kongestia — {name}"
    else:
        headline = f"Zwolniony ruch na {name}"

    cause = _cause_text(situation)
    recommendation = _recommendation(situation, situation.get("linked_incident") is not None)
    driver_act = _driver_action(situation)

    pred = situation.get("prediction")
    trend_txt = ""
    if pred:
        arrow = "rosnąca" if pred["rising"] else "stabilna lub malejąca"
        trend_txt = (
            f" Prognozowana tendencja: {arrow}. Przewidywany poziom kongestii w horyzoncie "
            f"{pred['horizon_minutes']} min wynosi {round(pred['predicted_ratio'] * 100)}%."
        )

    summary = (
        f"{headline}. Średni poziom kongestii w ostatniej godzinie: {round(situation['avg_ratio'] * 100)}% "
        f"(wartość szczytowa: {round(situation['max_ratio'] * 100)}%). "
        f"Zidentyfikowana przyczyna: {cause} "
        f"Rekomendacja operacyjna: {recommendation}{trend_txt}"
    )
    return {
        "headline": headline,
        "cause": cause,
        "recommendation": recommendation,
        "driver_action": driver_act,
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
        "driver_action": narrative.get("driver_action") or "",
        "linked_incident": situation.get("linked_incident"),
        "prediction": situation.get("prediction"),
        "cpi": situation.get("cpi"),
        "summary": narrative.get("summary") or "",
        "source": source,
    }


async def refresh_reports(limit: int = 8) -> List[Dict[str, Any]]:
    """Buduje sytuacje, generuje narracje przez Groq (z fallbackiem) i buforuje.

    Optymalizacja limitu Groq:
    - narracje stabilnych sytuacji sa brane z cache (bez zapytania),
    - tylko zmienione/nowe sytuacje ida do Groq w JEDNYM zbiorczym zapytaniu/cykl.
    """
    ts = time.time()
    situations = _build_situations(limit=20)[:limit]

    signatures = [_situation_signature(s) for s in situations]
    narratives: List[Optional[Dict[str, str]]] = [None] * len(situations)
    sources: List[str] = ["rule"] * len(situations)

    # 1) Reuzycie narracji z cache dla niezmienionych sytuacji.
    to_generate: List[int] = []
    for i, sig in enumerate(signatures):
        cached = _narrative_cache.get(sig)
        if cached:
            narratives[i] = cached["narrative"]
            sources[i] = cached["source"]
        else:
            to_generate.append(i)

    # 2) Jedno zbiorcze zapytanie do Groq dla zmienionych sytuacji.
    if to_generate and settings.groq_enabled and settings.groq_api_key:
        subset = [situations[i] for i in to_generate]
        async with httpx.AsyncClient(trust_env=False, timeout=settings.groq_timeout) as client:
            batch = await groq_client.generate_reports_batch(subset, client=client)
        for local_idx, global_idx in enumerate(to_generate):
            narrative = batch[local_idx]
            if narrative and (narrative.get("summary") or narrative.get("headline")):
                narratives[global_idx] = narrative
                sources[global_idx] = "groq"
                _narrative_cache[signatures[global_idx]] = {
                    "narrative": narrative,
                    "source": "groq",
                }

    # 3) Fallback regulowy dla pozostalych (brak Groq / blad / over-limit).
    reports: List[Dict[str, Any]] = []
    for i, situation in enumerate(situations):
        narrative = narratives[i]
        if narrative and (narrative.get("summary") or narrative.get("headline")):
            reports.append(_assemble(situation, narrative, sources[i], ts))
        else:
            reports.append(_assemble(situation, _rule_based_narrative(situation), "rule", ts))

    from backend.services.notifications.push import send_push_notification
    for r in reports:
        pid = r["point_id"]
        # Wyzwalacz: status critical lub zamknięta droga
        if r["level"] == "critical" or r["road_closure"]:
            last_push = _last_pushed_state.get(pid, 0)
            if ts - last_push > 1800:  # 30 minut cooldownu
                title = r.get("headline") or f"Utrudnienia: {r.get('point_name')}"
                body = r.get("recommendation") or "Spodziewaj się utrudnień na dojeździe do portu."
                # Asynchroniczne wywołanie by nie blokować cyklu (nieużywane w tym projekcie asynchro dla pusha, więc normalnie)
                send_push_notification(title, body)
                _last_pushed_state[pid] = ts

    # 4) Utrzymanie rozmiaru cache - tylko sygnatury z biezacego cyklu.
    active = set(signatures)
    for key in list(_narrative_cache.keys()):
        if key not in active:
            del _narrative_cache[key]

    _cache["ts"] = ts
    _cache["reports"] = reports
    return reports


def get_cached_reports(limit: int = 8) -> List[Dict[str, Any]]:
    return list(_cache.get("reports") or [])[:limit]


def cache_timestamp() -> Optional[float]:
    return _cache.get("ts")


async def generate_on_demand_global_report() -> Optional[Dict[str, Any]]:
    """Generuje globalny raport na zadanie (Groq), uwzgledniajac wszystkie wezly."""
    all_points = analysis.bottlenecks(limit=100)
    situations: List[Dict[str, Any]] = []
    
    for b in all_points:
        pid = b["point_id"]
        incident = _nearest_incident(b["port_id"], b.get("lat"), b.get("lon"))
        situations.append(
            {
                "point_id": pid,
                "point_name": b["point_name"],
                "port_id": b["port_id"],
                "level": b["level"],
                "avg_ratio": b["avg_ratio"],
                "weather": storage.latest_weather(b["port_id"]),
                "linked_incident": incident
            }
        )
    
    situations.sort(
        key=lambda s: (_SEVERITY.get(s["level"], 0), s["avg_ratio"]),
        reverse=True,
    )
    
    report = await groq_client.generate_global_report(situations[:20])
    
    if report:
        report["id"] = "global_ondemand"
        report["point_name"] = "Raport Calosciowy"
        report["level"] = "info"
        report["port_id"] = "GLOBAL"
        report["ts"] = time.time()
        return report
    
    return None
