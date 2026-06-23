"""Klient TRISTAR (ZDiZ Gdynia): system zarzadzania ruchem aglomeracji.

Dwa endpointy o roznym cyklu zycia:
- /ri/rest/road_segments      - statyczna geometria LineString segmentow (cache w pamieci).
- /ri/rest/traffic_intensities - zywe natezenie ruchu (pojazdy/h) per segment, co ~5 min.

TRISTAR nie zwraca predkosci, wiec nie da sie policzyc natywnego congestion_ratio.
Trzymamy surowa intensywnosc (intensity, poj/h) jako osobny sygnal; congestion_ratio
pozostaje None do czasu, az CPI policzy proxy wzgledem historii segmentu.

Mimo ze API teoretycznie obejmuje Trojmiasto, realny strumien intensywnosci jest
obecnie czysto gdynski - dlatego SEGMENT_MAP wiaze segmenty tylko z punktami Gdyni.
Wzbogacamy istniejace punkty, nie tworzymy nowych: kazdy rekord nosi point_id
istniejacego punktu, ale source='tristar'.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .ports import get_point

BASE_URL = "https://api.zdiz.gdynia.pl/ri/rest"

# Mapowanie segment TRISTAR -> istniejacy point_id (uzgodnione na realnych danych,
# KROK A). Tylko Gdynia - segmenty z zywym pomiarem najblizsze punktom portu.
SEGMENT_MAP: Dict[int, str] = {
    32689: "gdy_wisniewskiego",   # ~634 m, ul. J. Wisniewskiego (brama portu)
    34101: "gdy_kwiatkowskiego",  # ~1,5 km, estakada Kwiatkowskiego
    38543: "gdy_polska",          # ~1,7 km, rejon ul. Polska
}


@dataclass
class TristarReading:
    """Pojedynczy zywy pomiar natezenia dla zmapowanego segmentu."""

    segment_id: int
    point_id: str
    intensity: Optional[float]     # pojazdy / h
    measure_time: Optional[str]    # surowy znacznik z API (string)
    lat: Optional[float]           # midpoint geometrii segmentu
    lon: Optional[float]


class TristarClient:
    """Asynchroniczny klient TRISTAR. Endpointy publiczne - bez klucza API."""

    def __init__(self, timeout: float = 15.0) -> None:
        self._client = httpx.AsyncClient(timeout=timeout)
        # Cache midpointow geometrii: segment_id -> (lat, lon). Geometria jest
        # statyczna (lastUpdate 2018), wiec pobieramy ja raz na zycie procesu.
        self._segment_midpoints: Optional[Dict[int, Tuple[float, float]]] = None

    async def aclose(self) -> None:
        await self._client.aclose()

    # --- Geometria segmentow (statyczna, cache) ------------------------------
    async def _load_segment_geometry(self) -> Dict[int, Tuple[float, float]]:
        if self._segment_midpoints is not None:
            return self._segment_midpoints
        url = f"{BASE_URL}/road_segments"
        resp = await self._client.get(url)
        resp.raise_for_status()
        data = resp.json()
        midpoints: Dict[int, Tuple[float, float]] = {}
        for seg in (data.get("road_segments", []) or []):
            sid = seg.get("id")
            coords = ((seg.get("geometry") or {}).get("coordinates")) or []
            if sid is None or not coords:
                continue
            # coordinates: [[lon, lat], ...] (EPSG:4326). Bierzemy srodkowy wierzcholek.
            lon, lat = coords[len(coords) // 2][:2]
            midpoints[sid] = (lat, lon)
        self._segment_midpoints = midpoints
        return midpoints

    # --- Zywe natezenie ------------------------------------------------------
    async def get_intensities(self) -> List[TristarReading]:
        """Zwraca pomiary tylko dla segmentow z SEGMENT_MAP (reszte ignorujemy)."""
        midpoints = await self._load_segment_geometry()
        url = f"{BASE_URL}/traffic_intensities"
        resp = await self._client.get(url)
        resp.raise_for_status()
        data = resp.json()
        return self._parse_intensities(data, midpoints)

    @staticmethod
    def _parse_intensities(
        data: Any, midpoints: Dict[int, Tuple[float, float]]
    ) -> List[TristarReading]:
        readings: List[TristarReading] = []
        for item in data or []:
            sid = item.get("roadSegmentId")
            point_id = SEGMENT_MAP.get(sid)
            if point_id is None:
                continue
            lat, lon = midpoints.get(sid, (None, None))
            readings.append(
                TristarReading(
                    segment_id=sid,
                    point_id=point_id,
                    intensity=item.get("intensity"),
                    measure_time=item.get("measureTime"),
                    lat=lat,
                    lon=lon,
                )
            )
        return readings


def normalize(reading: TristarReading, ts: Optional[float] = None) -> Dict[str, Any]:
    """Znormalizowany rekord w schemacie measurements (z polami zrodlowymi).

    Wzbogaca istniejacy punkt: bierze port_id/point_name/road z ports.py, ale
    lat/lon to midpoint segmentu (warstwa odrebna geograficznie). Bez zapisu do bazy.
    """
    ts = ts if ts is not None else time.time()
    resolved = get_point(reading.point_id)
    port_id = resolved[0].id if resolved else None
    point_name = resolved[1].name if resolved else reading.point_id
    road = resolved[1].road if resolved else None
    return {
        "ts": ts,
        "port_id": port_id,
        "point_id": reading.point_id,
        "point_name": point_name,
        "road": road,
        "lat": reading.lat,
        "lon": reading.lon,
        "current_speed": None,
        "free_flow_speed": None,
        "congestion_ratio": None,      # brak predkosci w TRISTAR - proxy liczy CPI z historii
        "confidence": None,            # stara kolumna REAL (TomTom) - puste dla tristar
        "road_closure": 0,
        "source": "tristar",
        "confidence_label": "measured",
        "intensity": reading.intensity,
        "segment_id": reading.segment_id,
    }


async def fetch(ts: Optional[float] = None) -> List[Dict[str, Any]]:
    """Pobiera zywe natezenie i zwraca znormalizowane rekordy gotowe do zapisu.

    Schedulera ani zapisu do bazy tu nie ma - to dolozymy w KROKU B.
    """
    client = TristarClient()
    try:
        readings = await client.get_intensities()
    finally:
        await client.aclose()
    ts = ts if ts is not None else time.time()
    return [normalize(r, ts) for r in readings]
