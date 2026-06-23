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


def predict_trends() -> List[Dict[str, Any]]:
    """Krotkoterminowa predykcja: regresja liniowa congestion ratio w czasie.

    Zwraca prognoze ratio na horyzont prediction_horizon_minutes oraz flage
    'rising' gdy trend narasta powyzej progu.
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

        # --- Augmentacja zywymi zrodlami (backend, schemat wyjscia zachowany) ---
        # Presja portu (zywe statki + Codeco) jako narastajacy popyt na ciezarowki.
        pp = portdata.port_pressure_for_point(point_id, settings.pred_port_lookahead_h)
        port_term = settings.pred_port_weight * pp["total"]
        # TRISTAR (Gdynia): nadwyzka natezenia ponad typowe.
        tri_load = _tristar_load_excess(point_id)
        tri_term = settings.pred_tristar_weight * tri_load

        predicted = max(0.0, min(1.0, base_pred + port_term + tri_term))
        current = float(ratios[-1])
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
                "horizon_minutes": horizon,
                "rising": bool(rising),
                "samples": len(series),
                "ts": last.get("ts"),
                # Pola informacyjne (front ich nie renderuje) - rozklad wplywu zrodel:
                "predicted_ratio_base": round(base_pred, 3),
                "port_pressure": round(pp["total"], 3),
                "port_pressure_ship": (pp.get("dominant_ship") or {}).get("name"),
                "tristar_load": round(tri_load, 3),
            }
        )

    predictions.sort(key=lambda x: x["slope_per_10min"], reverse=True)
    return predictions
