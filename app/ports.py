"""Definicje portow i monitorowanych punktow na drogach dojazdowych do terminali.

Zakres ograniczony do aglomeracji Trojmiasta (Gdansk, Gdynia) - dane TomTom oraz
wskazniki na mapie dotycza wylacznie okolic Trojmiasta.

Wspolrzedne to wartosci startowe do kalibracji na mapie. Drogi wewnatrz portow
sa zwykle prywatne i poza danymi TomTom, dlatego monitorujemy obwodnice oraz
glowne trasy dojazdowe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass(frozen=True)
class MonitoredPoint:
    """Pojedynczy punkt pomiarowy na drodze dojazdowej."""

    id: str
    name: str
    lat: float
    lon: float
    road: str  # nazwa drogi / trasy


@dataclass(frozen=True)
class Port:
    """Port wraz z lista punktow i bbox uzywanym do zapytan o incydenty.

    bbox: (min_lon, min_lat, max_lon, max_lat) w EPSG:4326.
    """

    id: str
    name: str
    center: Tuple[float, float]  # (lat, lon) - srodek mapy
    bbox: Tuple[float, float, float, float]
    points: List[MonitoredPoint] = field(default_factory=list)
    zoom: int = 12  # poziom przyblizenia mapy po wyborze portu


PORTS: List[Port] = [
    Port(
        id="gdansk",
        name="Port Gdansk",
        center=(54.3795, 18.6800),
        bbox=(18.580, 54.330, 18.780, 54.430),
        points=[
            MonitoredPoint(
                id="gda_sucharskiego",
                name="Trasa Sucharskiego",
                lat=54.3705,
                lon=18.7110,
                road="Trasa Sucharskiego (S7/DK91)",
            ),
            MonitoredPoint(
                id="gda_marynarki_polskiej",
                name="ul. Marynarki Polskiej",
                lat=54.3870,
                lon=18.6560,
                road="ul. Marynarki Polskiej",
            ),
            MonitoredPoint(
                id="gda_tunel",
                name="Tunel pod Martwa Wisla",
                lat=54.3950,
                lon=18.6960,
                road="Trasa Slowackiego / tunel",
            ),
            MonitoredPoint(
                id="gda_dct",
                name="DCT / ul. Kontenerowa",
                lat=54.3940,
                lon=18.7060,
                road="ul. Kontenerowa (terminal DCT)",
            ),
            MonitoredPoint(
                id="gda_ku_ujsciu",
                name="ul. Ku Ujsciu (Port Polnocny)",
                lat=54.4020,
                lon=18.7000,
                road="ul. Ku Ujsciu",
            ),
            MonitoredPoint(
                id="gda_elblaska",
                name="ul. Elblaska (dojazd)",
                lat=54.3760,
                lon=18.6850,
                road="ul. Elblaska (DK91)",
            ),
        ],
    ),
    Port(
        id="gdynia",
        name="Port Gdynia",
        center=(54.5350, 18.5300),
        bbox=(18.470, 54.490, 18.600, 54.580),
        points=[
            MonitoredPoint(
                id="gdy_kwiatkowskiego",
                name="Estakada Kwiatkowskiego",
                lat=54.5430,
                lon=18.5070,
                road="Estakada Kwiatkowskiego",
            ),
            MonitoredPoint(
                id="gdy_wisniewskiego",
                name="ul. Janka Wisniewskiego",
                lat=54.5290,
                lon=18.5400,
                road="ul. Janka Wisniewskiego",
            ),
            MonitoredPoint(
                id="gdy_polska",
                name="ul. Polska (brama portu)",
                lat=54.5325,
                lon=18.5480,
                road="ul. Polska",
            ),
            MonitoredPoint(
                id="gdy_energetykow",
                name="ul. Energetykow (BCT)",
                lat=54.5270,
                lon=18.5300,
                road="ul. Energetykow (terminal BCT)",
            ),
            MonitoredPoint(
                id="gdy_morska",
                name="Droga Gdynska / Morska",
                lat=54.5270,
                lon=18.5150,
                road="Droga Gdynska (DK6) / ul. Morska",
            ),
            MonitoredPoint(
                id="gdy_wendy",
                name="ul. Wendy (nabrzeze)",
                lat=54.5200,
                lon=18.5470,
                road="ul. Wendy",
            ),
        ],
    ),
    Port(
        id="szczecin_swinoujscie",
        name="Port Szczecin-Swinoujscie",
        center=(53.6600, 14.4300),
        bbox=(14.150, 53.350, 14.750, 53.950),
        zoom=10,
        points=[
            MonitoredPoint(
                id="szcz_swin_s3",
                name="Droga S3 (dojazd)",
                lat=53.8650,
                lon=14.2880,
                road="Droga ekspresowa S3",
            ),
            MonitoredPoint(
                id="szcz_gdanska",
                name="ul. Gdanska (Szczecin)",
                lat=53.4190,
                lon=14.5680,
                road="ul. Gdanska",
            ),
            MonitoredPoint(
                id="swin_finska",
                name="ul. Finska/Dunska",
                lat=53.9030,
                lon=14.2650,
                road="ul. Finska / Dunska",
            ),
            MonitoredPoint(
                id="swin_promowy",
                name="Terminal promowy Swinoujscie",
                lat=53.9090,
                lon=14.2790,
                road="ul. Dworcowa (terminal promowy)",
            ),
            MonitoredPoint(
                id="szcz_bytomska",
                name="ul. Bytomska (Port Szczecin)",
                lat=53.4180,
                lon=14.5850,
                road="ul. Bytomska",
            ),
            MonitoredPoint(
                id="szcz_struga",
                name="ul. Struga (DK10)",
                lat=53.4000,
                lon=14.6050,
                road="ul. Struga (DK10)",
            ),
        ],
    ),
]


def all_points() -> List[Tuple[Port, MonitoredPoint]]:
    """Splaszczona lista (port, punkt) dla calego pollingu."""
    return [(port, point) for port in PORTS for point in port.points]


def get_port(port_id: str) -> Port | None:
    return next((p for p in PORTS if p.id == port_id), None)


def get_point(point_id: str) -> Tuple[Port, MonitoredPoint] | None:
    for port in PORTS:
        for point in port.points:
            if point.id == point_id:
                return port, point
    return None
