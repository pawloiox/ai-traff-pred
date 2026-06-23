"""Modul pogodowy: polling Open-Meteo API i obliczanie weather_penalty.

Open-Meteo jest darmowy i nie wymaga klucza API. Polling co 30 min per port
(3 porty = 3 zapytan / 30 min - daleko ponizej limitu).

Weather codes (WMO): https://open-meteo.com/en/docs
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from .ports import PORTS

logger = logging.getLogger("port_traffic_pulse.weather")

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def _compute_weather_penalty(
    rain: Optional[float],
    wind_speed: Optional[float],
    visibility: Optional[float],
    weather_code: Optional[int],
) -> float:
    """Oblicza kare pogodowa [0.0 - 1.0] na podstawie warunkow atmosferycznych.

    Skladniki (addytywne, cap 1.0):
    - Deszcz (rain > 0):      +0.15 lekki, +0.30 umiarkowany/silny
    - Wiatr (> 40 km/h):      +0.10 umiarkowany, +0.20 silny (>60)
    - Widocznosc (< 2000m):   +0.15 ograniczona, +0.30 silnie ograniczona (<500m)
    - Snieg/zamieci (WMO 71+): +0.30 snieg, +0.50 zamieci
    """
    penalty = 0.0

    # Deszcz (mm/h w biezacej godzinie)
    if rain is not None and rain > 0:
        if rain >= 2.5:
            penalty += 0.30  # umiarkowany/silny deszcz
        else:
            penalty += 0.15  # lekki deszcz

    # Wiatr (km/h)
    if wind_speed is not None:
        if wind_speed >= 60:
            penalty += 0.20  # silny wiatr
        elif wind_speed >= 40:
            penalty += 0.10  # umiarkowany wiatr

    # Widocznosc (metry)
    if visibility is not None:
        if visibility < 500:
            penalty += 0.30  # bardzo slaba widocznosc
        elif visibility < 2000:
            penalty += 0.15  # ograniczona widocznosc

    # Snieg / zamieci (WMO weather codes)
    if weather_code is not None:
        if weather_code in (75, 77, 85, 86):
            penalty += 0.50  # intensywny snieg / zamieci
        elif weather_code in (71, 73):
            penalty += 0.30  # lekki/umiarkowany snieg
        elif weather_code in (56, 57, 66, 67):
            penalty += 0.25  # marznacy deszcz / sleet

    return min(1.0, penalty)


async def fetch_weather_for_port(
    lat: float, lon: float, client: Optional[httpx.AsyncClient] = None
) -> Dict[str, Any]:
    """Pobiera biezaca pogode z Open-Meteo dla podanych wspolrzednych."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,rain,wind_speed_10m,visibility,weather_code",
        "timezone": "Europe/Warsaw",
    }

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=15.0)
    try:
        resp = await client.get(OPEN_METEO_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
        current = data.get("current", {})

        temperature = current.get("temperature_2m")
        rain = current.get("rain")
        wind_speed = current.get("wind_speed_10m")
        visibility = current.get("visibility")
        weather_code = current.get("weather_code")

        penalty = _compute_weather_penalty(rain, wind_speed, visibility, weather_code)

        return {
            "temperature": temperature,
            "rain": rain,
            "wind_speed": wind_speed,
            "visibility": visibility,
            "weather_code": weather_code,
            "weather_penalty": round(penalty, 3),
        }
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("Open-Meteo blad dla (%.2f, %.2f): %s", lat, lon, exc)
        return {
            "temperature": None,
            "rain": None,
            "wind_speed": None,
            "visibility": None,
            "weather_code": None,
            "weather_penalty": 0.0,
        }
    finally:
        if owns_client and client is not None:
            await client.aclose()


async def fetch_all_ports() -> List[Dict[str, Any]]:
    """Pobiera pogode dla wszystkich portow. Zwraca liste slownikow z port_id."""
    results: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        for port in PORTS:
            lat, lon = port.center
            weather = await fetch_weather_for_port(lat, lon, client=client)
            weather["port_id"] = port.id
            results.append(weather)
            logger.info(
                "Pogoda %s: %.1f°C, deszcz=%.1f mm, wiatr=%.0f km/h, penalty=%.2f",
                port.id,
                weather.get("temperature") or 0,
                weather.get("rain") or 0,
                weather.get("wind_speed") or 0,
                weather.get("weather_penalty", 0),
            )
    return results


def get_weather_penalty(port_id: str) -> float:
    """Zwraca biezacy weather_penalty dla portu z cache (storage).

    Uzywane synchronicznie przez scoring w analysis.py.
    """
    from .storage import storage

    row = storage.latest_weather(port_id)
    if row is None:
        return 0.0
    return float(row.get("weather_penalty", 0.0))
