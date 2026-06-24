"""Klient TomTom Traffic API: Flow Segment Data, Incident Details v5 oraz
buildery URL kafelkow rastrowych (baza, flow, incidents)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .config import settings

BASE_URL = "https://api.tomtom.com"

# Mapowanie kategorii incydentow TomTom (iconCategory, Incident Details v5) na etykiety PL.
INCIDENT_CATEGORIES: Dict[int, str] = {
    0: "Nieznane",
    1: "Wypadek",
    2: "Mgla",
    3: "Niebezpieczne warunki",
    4: "Deszcz",
    5: "Oblodzenie",
    6: "Zator / korek",
    7: "Zamkniety pas",
    8: "Zamkniecie drogi",
    9: "Roboty drogowe",
    10: "Silny wiatr",
    11: "Powodz / zalanie",
    14: "Pojazd unieruchomiony",
}


@dataclass
class FlowResult:
    current_speed: Optional[float]
    free_flow_speed: Optional[float]
    current_travel_time: Optional[int]
    free_flow_travel_time: Optional[int]
    confidence: Optional[float]
    road_closure: bool
    coordinates: List[Tuple[float, float]]  # [(lat, lon), ...]

    @property
    def congestion_ratio(self) -> Optional[float]:
        """0.0 = plynnie, ~1.0 = stoi. None gdy brak danych."""
        if self.road_closure:
            return 1.0
        if not self.free_flow_speed or self.free_flow_speed <= 0:
            return None
        if self.current_speed is None:
            return None
        ratio = 1.0 - (self.current_speed / self.free_flow_speed)
        return max(0.0, min(1.0, ratio))


@dataclass
class Incident:
    id: str
    category: int
    category_label: str
    description: str
    delay_seconds: Optional[int]
    magnitude: Optional[int]
    from_name: Optional[str]
    to_name: Optional[str]
    coordinates: List[Tuple[float, float]]  # [(lat, lon), ...]

    @property
    def representative_point(self) -> Optional[Tuple[float, float]]:
        if not self.coordinates:
            return None
        return self.coordinates[len(self.coordinates) // 2]


class TomTomClient:
    """Asynchroniczny klient TomTom Traffic API."""

    def __init__(self, api_key: Optional[str] = None, timeout: float = 15.0) -> None:
        self.api_key = api_key or settings.tomtom_api_key
        self._client = httpx.AsyncClient(trust_env=False, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    # --- Flow Segment Data ---------------------------------------------------
    async def get_flow(
        self, lat: float, lon: float, style: str = "absolute", zoom: int = 10
    ) -> FlowResult:
        url = f"{BASE_URL}/traffic/services/4/flowSegmentData/{style}/{zoom}/json"
        params = {
            "key": self.api_key,
            "point": f"{lat},{lon}",
            "unit": "KMPH",
        }
        resp = await self._client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        return self._parse_flow(data)

    @staticmethod
    def _parse_flow(data: Dict[str, Any]) -> FlowResult:
        seg = data.get("flowSegmentData", {}) or {}
        coords: List[Tuple[float, float]] = []
        for c in (seg.get("coordinates", {}) or {}).get("coordinate", []) or []:
            lat = c.get("latitude")
            lon = c.get("longitude")
            if lat is not None and lon is not None:
                coords.append((lat, lon))
        return FlowResult(
            current_speed=seg.get("currentSpeed"),
            free_flow_speed=seg.get("freeFlowSpeed"),
            current_travel_time=seg.get("currentTravelTime"),
            free_flow_travel_time=seg.get("freeFlowTravelTime"),
            confidence=seg.get("confidence"),
            road_closure=bool(seg.get("roadClosure", False)),
            coordinates=coords,
        )

    # --- Incident Details v5 -------------------------------------------------
    async def get_incidents(
        self, bbox: Tuple[float, float, float, float], language: str = "pl-PL"
    ) -> List[Incident]:
        url = f"{BASE_URL}/traffic/services/5/incidentDetails"
        fields = (
            "{incidents{type,geometry{type,coordinates},"
            "properties{id,iconCategory,magnitudeOfDelay,events{description,code},"
            "delay,from,to}}}"
        )
        params = {
            "key": self.api_key,
            "bbox": ",".join(str(v) for v in bbox),
            "fields": fields,
            "language": language,
            "timeValidityFilter": "present",
        }
        resp = await self._client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        return self._parse_incidents(data)

    @staticmethod
    def _parse_incidents(data: Dict[str, Any]) -> List[Incident]:
        incidents: List[Incident] = []
        for item in data.get("incidents", []) or []:
            props = item.get("properties", {}) or {}
            geom = item.get("geometry", {}) or {}
            coords = _extract_latlon(geom)

            events = props.get("events", []) or []
            description = "; ".join(
                e.get("description", "") for e in events if e.get("description")
            ) or "Brak opisu"

            category = props.get("iconCategory", 0) or 0
            incidents.append(
                Incident(
                    id=str(props.get("id", "")),
                    category=category,
                    category_label=INCIDENT_CATEGORIES.get(category, "Inne"),
                    description=description,
                    delay_seconds=props.get("delay"),
                    magnitude=props.get("magnitudeOfDelay"),
                    from_name=props.get("from"),
                    to_name=props.get("to"),
                    coordinates=coords,
                )
            )
        return incidents

    # --- Buildery URL kafelkow (do uzycia we froncie) ------------------------
    def basemap_tile_url(self) -> str:
        return f"{BASE_URL}/map/1/tile/basic/night/{{z}}/{{x}}/{{y}}.png?key={self.api_key}"

    def basemap_tile_url_light(self) -> str:
        return f"{BASE_URL}/map/1/tile/basic/main/{{z}}/{{x}}/{{y}}.png?key={self.api_key}"

    def flow_tile_url(self, style: str = "relative0") -> str:
        return (
            f"{BASE_URL}/traffic/map/4/tile/flow/{style}/"
            f"{{z}}/{{x}}/{{y}}.png?key={self.api_key}"
        )

    def incidents_tile_url(self, style: str = "s3") -> str:
        return (
            f"{BASE_URL}/traffic/map/4/tile/incidents/{style}/"
            f"{{z}}/{{x}}/{{y}}.png?key={self.api_key}"
        )


def _extract_latlon(geometry: Dict[str, Any]) -> List[Tuple[float, float]]:
    """GeoJSON-owe coordinates TomTom sa w formacie [lon, lat]. Zwracamy (lat, lon)."""
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    result: List[Tuple[float, float]] = []
    if not coords:
        return result

    def add_point(pair: Any) -> None:
        if isinstance(pair, (list, tuple)) and len(pair) >= 2:
            lon, lat = pair[0], pair[1]
            result.append((lat, lon))

    if gtype == "Point":
        add_point(coords)
    elif gtype == "LineString":
        for pair in coords:
            add_point(pair)
    elif gtype == "MultiLineString":
        for line in coords:
            for pair in line:
                add_point(pair)
    else:
        # Fallback: probujemy splaszczyc cokolwiek przyjdzie.
        for pair in coords:
            add_point(pair)
    return result
