"""Klient ZDiTM Szczecin: pozycje GPS pojazdow komunikacji miejskiej jako proxy ruchu.

Endpoint /api/v1/vehicles zwraca biezace pozycje autobusow i tramwajow (predkosc,
namiar, przystanki) odswiezane co ~10 s. Predkosc traktujemy jako proxy plynnosci
ruchu na drodze - to slabszy sygnal niz pomiar TomTom/TRISTAR, stad confidence='proxy'.

Pulapka: pojazd stojacy na przystanku ma velocity=0, co NIE jest korkiem (flaga
'stuck' z API jest niewypelniona). Dlatego dla punktu zbieramy pojazdy w promieniu R
i bierzemy 75. percentyl predkosci - jesli chocby czesc pojazdow jedzie plynnie,
droga nie stoi; dopiero gdy wszystkie sa wolne, mamy realny zator.

Pokrywa wylacznie miasto Szczecin (siec ZDiTM) - dlatego POINT_IDS zawiera tylko
szcz_gdanska. Swinoujscie ma osobna komunikacje, poza tym API (najblizszy pojazd ~35 km).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
import numpy as np

from .config import settings
from .ports import get_point

VEHICLES_URL = "https://www.zditm.szczecin.pl/api/v1/vehicles"

# Punkty wzbogacane przez ZDiTM (tylko miasto Szczecin - patrz docstring).
POINT_IDS: List[str] = ["szcz_gdanska"]


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    p = math.pi / 180.0
    a = (
        0.5
        - math.cos((lat2 - lat1) * p) / 2
        + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2
    )
    return 2 * R * math.asin(math.sqrt(a))


@dataclass
class ZditmAggregate:
    """Zagregowany proxy ruchu dla jednego monitorowanego punktu."""

    point_id: str
    vehicle_count: int
    p75_speed: float          # 75. percentyl predkosci pobliskich pojazdow [km/h]
    measure_time: Optional[str]  # najswiezszy updated_at sposrod uzytych pojazdow


def _aggregate(vehicles: List[Dict[str, Any]]) -> List[ZditmAggregate]:
    """Dla kazdego punktu z POINT_IDS skupia pojazdy w promieniu i liczy p75 predkosci."""
    radius = settings.zditm_radius_m
    out: List[ZditmAggregate] = []
    for point_id in POINT_IDS:
        resolved = get_point(point_id)
        if resolved is None:
            continue
        _, point = resolved
        nearby = [
            v
            for v in vehicles
            if v.get("latitude") is not None
            and v.get("longitude") is not None
            and _haversine_m(point.lat, point.lon, v["latitude"], v["longitude"]) <= radius
        ]
        if not nearby:
            continue  # brak pojazdow w zasiegu - luka, jak przy braku danych
        speeds = [float(v.get("velocity") or 0.0) for v in nearby]
        p75 = float(np.percentile(speeds, 75))
        times = [v.get("updated_at") for v in nearby if v.get("updated_at")]
        out.append(
            ZditmAggregate(
                point_id=point_id,
                vehicle_count=len(nearby),
                p75_speed=p75,
                measure_time=max(times) if times else None,
            )
        )
    return out


def normalize(agg: ZditmAggregate, ts: Optional[float] = None) -> Dict[str, Any]:
    """Znormalizowany rekord w schemacie measurements (warstwa 'zditm', confidence proxy).

    current_speed = p75 predkosci, free_flow_speed = V_ref miejski; congestion_ratio
    liczone ta sama formula co TomTom (1 - cur/free, przyciete do [0,1]).
    """
    ts = ts if ts is not None else time.time()
    vref = settings.zditm_freeflow_kmph
    ratio: Optional[float] = None
    if vref > 0:
        ratio = max(0.0, min(1.0, 1.0 - agg.p75_speed / vref))

    resolved = get_point(agg.point_id)
    port_id = resolved[0].id if resolved else None
    point = resolved[1] if resolved else None
    return {
        "ts": ts,
        "port_id": port_id,
        "point_id": agg.point_id,
        "point_name": point.name if point else agg.point_id,
        "road": point.road if point else None,
        "lat": point.lat if point else None,
        "lon": point.lon if point else None,
        "current_speed": round(agg.p75_speed, 1),
        "free_flow_speed": vref,
        "congestion_ratio": round(ratio, 3) if ratio is not None else None,
        "confidence": None,            # stara kolumna REAL (TomTom) - puste dla zditm
        "road_closure": 0,
        "source": "zditm",
        "confidence_label": "proxy",
        "intensity": None,             # ZDiTM nie daje natezenia - proxy z predkosci
    }


async def fetch(ts: Optional[float] = None) -> List[Dict[str, Any]]:
    """Pobiera pozycje pojazdow i zwraca znormalizowane rekordy gotowe do zapisu.

    Schedulera ani zapisu do bazy tu nie ma - to dolozymy w wpieciu schedulera (KROK C).
    """
    client = httpx.AsyncClient(trust_env=False, timeout=15.0)
    try:
        resp = await client.get(VEHICLES_URL)
        resp.raise_for_status()
        data = resp.json()
    finally:
        await client.aclose()
    vehicles = data.get("data", []) if isinstance(data, dict) else (data or [])
    ts = ts if ts is not None else time.time()
    return [normalize(agg, ts) for agg in _aggregate(vehicles)]
