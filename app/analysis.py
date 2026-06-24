"""Analityka ruchu: poziomy kongestii, ranking waskich gardel, detekcja anomalii
i krotkoterminowa predykcja narastania korkow.

Wszystkie funkcje pracuja na danych z warstwy storage (SQLite).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import numpy as np

from . import portdata
from .config import settings
from .storage import storage


def level_for_ratio(ratio: Optional[float], road_closure: bool = False) -> str:
    """Zwraca poziom: ok / warning / critical / unknown."""
    if road_closure:
        return "critical"
    if ratio is None:
        return "unknown"
    if ratio >= settings.ratio_critical:
        return "critical"
    if ratio >= settings.ratio_warning:
        return "warning"
    return "ok"


def current_status() -> List[Dict[str, Any]]:
    """Biezacy stan kazdego punktu z poziomem kongestii."""
    rows = storage.latest_measurements()
    result: List[Dict[str, Any]] = []
    for r in rows:
        closure = bool(r.get("road_closure"))
        ratio = r.get("congestion_ratio")
        result.append(
            {
                **r,
                "road_closure": closure,
                "level": level_for_ratio(ratio, closure),
            }
        )
    result.sort(key=lambda x: (x.get("congestion_ratio") or 0.0), reverse=True)
    return result


def bottlenecks(window_minutes: Optional[int] = None, limit: int = 10) -> List[Dict[str, Any]]:
    """Ranking waskich gardel z ostatniego okna czasu.

    Sortowanie po sredniej kongestii w oknie; raportujemy tez maksimum i liczbe probek.
    """
    window = window_minutes or settings.bottleneck_window_minutes
    since = time.time() - window * 60
    rows = storage.measurements_since(since)

    by_point: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        ratio = r.get("congestion_ratio")
        if ratio is None:
            continue
        pid = r["point_id"]
        bucket = by_point.setdefault(
            pid,
            {
                "point_id": pid,
                "point_name": r["point_name"],
                "road": r.get("road"),
                "port_id": r["port_id"],
                "lat": r.get("lat"),
                "lon": r.get("lon"),
                "_ratios": [],
                "closures": 0,
                "last_ts": 0.0,
            },
        )
        bucket["_ratios"].append(ratio)
        if r.get("ts") and r["ts"] > bucket["last_ts"]:
            bucket["last_ts"] = r["ts"]
        if r.get("road_closure"):
            bucket["closures"] += 1

    ranked: List[Dict[str, Any]] = []
    for b in by_point.values():
        ratios = b.pop("_ratios")
        if not ratios:
            continue
        avg = float(np.mean(ratios))
        b["avg_ratio"] = round(avg, 3)
        b["max_ratio"] = round(float(np.max(ratios)), 3)
        b["samples"] = len(ratios)
        b["level"] = level_for_ratio(avg, b["closures"] > 0)
        ranked.append(b)

    ranked.sort(key=lambda x: x["avg_ratio"], reverse=True)
    return ranked[:limit]


def _series_for_point(
    point_id: str, window_minutes: int, sources: tuple = ("tomtom",)
) -> List[Dict[str, Any]]:
    since = time.time() - window_minutes * 60
    if sources == ("tomtom",):
        rows = storage.measurements_since(since, point_id=point_id)
    else:
        rows = storage.measurements_since(since, point_id=point_id, source=None)
        rows = [r for r in rows if r.get("source") in sources]
    return [r for r in rows if r.get("congestion_ratio") is not None]


def _tristar_load_excess(point_id: str) -> float:
    """Wzgledna nadwyzka natezenia TRISTAR (Gdynia) ponad mediane z ostatnich godzin [0,1].

    TRISTAR daje natezenie (poj/h), nie predkosc - wiec uzywamy go jako sygnalu
    'nietypowo wysokie obciazenie drogi', nie wprost kongestii.
    """
    since = time.time() - 6 * 3600
    rows = storage.measurements_since(since, point_id=point_id, source="tristar")
    vals = [r["intensity"] for r in rows if r.get("intensity")]
    if len(vals) < 3:
        return 0.0
    med = float(np.median(vals))
    if med <= 0:
        return 0.0
    return max(0.0, min(1.0, (vals[-1] - med) / med))


def detect_anomalies() -> List[Dict[str, Any]]:
    """Wykrywa punkty, w ktorych biezacy ratio mocno odbiega od baseline.

    Baseline = srednia i odchylenie z historii punktu (rolling). Jesli probek za malo,
    stosujemy fallback progowy (krytyczny poziom = anomalia).
    """
    anomalies: List[Dict[str, Any]] = []
    latest = {r["point_id"]: r for r in storage.latest_measurements()}

    # Baseline z ostatnich kilku godzin.
    baseline_window = 6 * 60
    for point_id, last in latest.items():
        current = last.get("congestion_ratio")
        if current is None:
            continue
        series = _series_for_point(point_id, baseline_window)
        ratios = [r["congestion_ratio"] for r in series]

        if len(ratios) < settings.anomaly_min_samples:
            # Fallback: brak baseline - sygnalizujemy tylko silny zator.
            if level_for_ratio(current, bool(last.get("road_closure"))) == "critical":
                anomalies.append(
                    {
                        "point_id": point_id,
                        "point_name": last["point_name"],
                        "road": last.get("road"),
                        "port_id": last["port_id"],
                        "current_ratio": round(current, 3),
                        "zscore": None,
                        "reason": "Silny zator (brak danych historycznych do baseline)",
                    }
                )
            continue

        mean = float(np.mean(ratios))
        std = float(np.std(ratios))
        if std < 1e-6:
            continue
        z = (current - mean) / std
        if z >= settings.anomaly_zscore_threshold and current > settings.ratio_warning:
            anomalies.append(
                {
                    "point_id": point_id,
                    "point_name": last["point_name"],
                    "road": last.get("road"),
                    "port_id": last["port_id"],
                    "current_ratio": round(current, 3),
                    "baseline_ratio": round(mean, 3),
                    "zscore": round(z, 2),
                    "reason": f"Kongestia {round(current * 100)}% znacznie powyzej typowej {round(mean * 100)}%",
                }
            )

    anomalies.sort(key=lambda x: x.get("zscore") or 0.0, reverse=True)
    return anomalies


def predict_trends(horizon_hours: int = 1) -> List[Dict[str, Any]]:
    """Predykcja kongestii z wykorzystaniem modelu ML (XGBoost) na wybrany horyzont.

    Gdy model ML nie jest gotowy, uzywa regresji liniowej z krotszym horyzontem jako fallback.
    """
    predictions: List[Dict[str, Any]] = []
    latest = {r["point_id"]: r for r in storage.latest_measurements()}

    for point_id, last in latest.items():
        # Szereg trendu uwzglednia ZDiTM (proxy ratio) obok TomTom - zywy wplyw na trend.
        series = _series_for_point(
            point_id, settings.prediction_window_minutes, sources=("tomtom", "zditm")
        )
        if len(series) < 3:
            continue

        ts = np.array([r["ts"] for r in series], dtype=float)
        ratios = np.array([r["congestion_ratio"] for r in series], dtype=float)

        # Czas w minutach wzgledem pierwszej probki dla stabilnosci numerycznej.
        t_min = (ts - ts[0]) / 60.0
        slope, intercept = np.polyfit(t_min, ratios, 1)  # ratio na minute

        now_min = t_min[-1]
        horizon = settings.prediction_horizon_minutes
        base_pred = float(slope * (now_min + horizon) + intercept)
        base_pred = max(0.0, min(1.0, base_pred))

        slope_per_10min = slope * 10.0

        # --- Predykcja XGBoost lub Fallback ---
        from . import ml, weather
        
        current = float(ratios[-1])
        pp = portdata.port_pressure_for_point(point_id, horizon_hours)
        port_term = pp["total"]
        
        try:
            if ml.is_model_ready():
                w_penalty = weather.get_weather_penalty(last["port_id"])
                predicted = ml.predict_horizon(
                    current_ratio=current,
                    weather_penalty=w_penalty,
                    port_pressure=port_term,
                    horizon_hours=horizon_hours,
                    point_id=point_id,
                )
            else:
                raise ValueError("ML model not ready")
        except ValueError:
            # Fallback: Krotkoterminowa regresja liniowa
            horizon_mins = horizon_hours * 60
            base_pred = float(slope * (now_min + horizon_mins) + intercept)
            base_pred = max(0.0, min(1.0, base_pred))
            tri_load = _tristar_load_excess(point_id)
            tri_term = settings.pred_tristar_weight * tri_load
            port_weight_scaled = settings.pred_port_weight * port_term
            predicted = max(0.0, min(1.0, base_pred + port_weight_scaled + tri_term))

        rising = (predicted - current >= settings.prediction_rising_slope) or (
            slope_per_10min >= settings.prediction_rising_slope
        )

        predictions.append(
            {
                "point_id": point_id,
                "point_name": last["point_name"],
                "road": last.get("road"),
                "port_id": last["port_id"],
                "current_ratio": round(current, 3),
                "slope_per_10min": round(float(slope_per_10min), 4),
                "predicted_ratio": round(predicted, 3),
                "horizon_minutes": horizon_hours * 60,
                "rising": bool(rising),
                "samples": len(series),
                "ts": last.get("ts"),
                "port_pressure": round(port_term, 3),
                "ml_active": ml.is_model_ready(),
            }
        )

    predictions.sort(key=lambda x: x["predicted_ratio"], reverse=True)
    return predictions


# --- Ulepszony scoring predykcji: delay_risk_score ---
# Formula z planu rozwoju (Osoba 3):
# delay_risk_score = (traffic_ratio_live * 0.4) + (historical_anomaly * 0.3)
#                  + (weather_penalty * 0.1) + (port_ship_penalty * 0.1)
#                  + (temporal_peak_penalty * 0.1)

_RISK_LEVELS = [
    (30, "low", "Jedź teraz — brak opóźnień"),
    (60, "medium", "Zmień trasę"),
    (80, "high", "Poczekaj w strefie buforowej"),
    (100, "very_high", "Wysokie ryzyko opóźnienia — firma powinna powiadomić klienta"),
]


def _risk_level(score: float) -> dict:
    """Mapuje score [0-100] na poziom ryzyka."""
    for threshold, level, label in _RISK_LEVELS:
        if score <= threshold:
            return {"level": level, "label": label, "threshold": threshold}
    return {"level": "very_high", "label": _RISK_LEVELS[-1][2], "threshold": 100}


def compute_delay_risk_score(point_id: str) -> Dict[str, Any]:
    """Oblicza delay_risk_score dla pojedynczego punktu.

    Zwraca slownik z wynikiem, rozkladem na skladniki i poziomem ryzyka.
    """
    from . import temporal, weather

    # 1. traffic_ratio_live (biezacy congestion ratio)
    latest = storage.latest_measurements()
    point_data = next((r for r in latest if r["point_id"] == point_id), None)
    if point_data is None:
        return {
            "point_id": point_id,
            "score": 0,
            "risk": _risk_level(0),
            "components": {},
            "error": "Brak danych pomiarowych",
        }

    traffic_ratio = point_data.get("congestion_ratio") or 0.0

    # 2. historical_anomaly (odchylenie od baseline)
    baseline_window = 6 * 60  # 6h
    series = [
        r["congestion_ratio"]
        for r in storage.measurements_since(
            time.time() - baseline_window * 60, point_id=point_id, source="tomtom"
        )
        if r.get("congestion_ratio") is not None
    ]
    if len(series) >= settings.anomaly_min_samples:
        mean = float(np.mean(series))
        std = float(np.std(series))
        if std > 1e-6:
            z = (traffic_ratio - mean) / std
            # Normalizacja z-score do [0, 1]: z >= 3 -> 1.0, z <= 0 -> 0.0
            historical_anomaly = max(0.0, min(1.0, z / 3.0))
        else:
            historical_anomaly = 0.0
    else:
        # Brak baseline: uzywamy samego ratio jako proxy
        historical_anomaly = traffic_ratio

    # 3. weather_penalty (z modulu pogodowego)
    port_id = point_data.get("port_id", "")
    weather_penalty = weather.get_weather_penalty(port_id)

    # 4. port_ship_penalty (presja portu)
    pp = portdata.port_pressure_for_point(point_id, settings.pred_port_lookahead_h)
    port_ship_penalty = float(pp["total"])

    # 5. temporal_peak_penalty
    tf = temporal.temporal_features()
    temporal_peak_penalty = tf["temporal_peak_penalty"]

    # Formula z PDF
    raw_score = (
        traffic_ratio * 0.4
        + historical_anomaly * 0.3
        + weather_penalty * 0.1
        + port_ship_penalty * 0.1
        + temporal_peak_penalty * 0.1
    )

    # Skalowanie do [0, 100]
    score = round(min(100.0, max(0.0, raw_score * 100)), 1)
    risk = _risk_level(score)

    return {
        "point_id": point_id,
        "point_name": point_data.get("point_name", ""),
        "port_id": port_id,
        "road": point_data.get("road", ""),
        "score": score,
        "risk": risk,
        "components": {
            "traffic_ratio_live": round(traffic_ratio, 3),
            "historical_anomaly": round(historical_anomaly, 3),
            "weather_penalty": round(weather_penalty, 3),
            "port_ship_penalty": round(port_ship_penalty, 3),
            "temporal_peak_penalty": round(temporal_peak_penalty, 3),
        },
        "temporal": {
            "is_rush_hour": tf["is_rush_hour"],
            "is_weekend": tf["is_weekend"],
            "is_holiday": tf["is_holiday"],
            "hour": tf["hour"],
            "day_of_week": tf["day_of_week"],
        },
        "ts": point_data.get("ts"),
    }


def delay_risk_all() -> List[Dict[str, Any]]:
    """Oblicza delay_risk_score dla wszystkich punktow.

    Zwraca liste posortowana malejaco po score.
    """
    latest = storage.latest_measurements()
    point_ids = [r["point_id"] for r in latest]
    results = [compute_delay_risk_score(pid) for pid in point_ids]
    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return results

