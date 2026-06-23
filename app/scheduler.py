"""Cykliczny polling TomTom: pobiera Flow Segment Data dla wszystkich punktow
oraz Incident Details dla bbox kazdego portu i zapisuje do storage."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import List

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import portcalls_live, tristar, zditm
from .config import settings
from .ports import PORTS, all_points
from .storage import storage
from .tomtom import TomTomClient

logger = logging.getLogger("port_traffic_pulse.scheduler")

_client: TomTomClient | None = None
_scheduler: AsyncIOScheduler | None = None
_last_poll_ts: float | None = None
_last_tristar_ts: float | None = None
_last_zditm_ts: float | None = None


def get_client() -> TomTomClient:
    global _client
    if _client is None:
        _client = TomTomClient()
    return _client


def last_poll_ts() -> float | None:
    return _last_poll_ts


def last_tristar_ts() -> float | None:
    return _last_tristar_ts


def last_zditm_ts() -> float | None:
    return _last_zditm_ts


async def _poll_flows() -> None:
    client = get_client()
    ts = time.time()
    tasks = []
    pairs = all_points()

    async def fetch(port, point):
        try:
            flow = await client.get_flow(point.lat, point.lon)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Flow blad dla %s: %s", point.id, exc)
            return
        storage.insert_measurement(
            {
                "ts": ts,
                "port_id": port.id,
                "point_id": point.id,
                "point_name": point.name,
                "road": point.road,
                "lat": point.lat,
                "lon": point.lon,
                "current_speed": flow.current_speed,
                "free_flow_speed": flow.free_flow_speed,
                "congestion_ratio": flow.congestion_ratio,
                "confidence": flow.confidence,
                "road_closure": 1 if flow.road_closure else 0,
            }
        )

    for port, point in pairs:
        tasks.append(fetch(port, point))
    await asyncio.gather(*tasks)


async def _poll_incidents() -> None:
    client = get_client()
    ts = time.time()

    async def fetch(port):
        try:
            incidents = await client.get_incidents(port.bbox)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Incidents blad dla %s: %s", port.id, exc)
            return
        rows = []
        for inc in incidents:
            pt = inc.representative_point
            rows.append(
                {
                    "snapshot_ts": ts,
                    "port_id": port.id,
                    "incident_id": inc.id,
                    "category": inc.category,
                    "category_label": inc.category_label,
                    "description": inc.description,
                    "delay_seconds": inc.delay_seconds,
                    "magnitude": inc.magnitude,
                    "from_name": inc.from_name,
                    "to_name": inc.to_name,
                    "lat": pt[0] if pt else None,
                    "lon": pt[1] if pt else None,
                }
            )
        storage.replace_incidents(port.id, ts, rows)

    await asyncio.gather(*(fetch(port) for port in PORTS))


async def poll_tristar() -> None:
    """Pobiera zywe natezenie TRISTAR (Gdynia) i zapisuje jako warstwe 'tristar'.

    Calkowicie niezalezne od joba TomTom - wlasny interwal, wlasna obsluga bledow.
    measureTime z API bywa przesuniety (strefa/snapshot), wiec logujemy go tylko
    informacyjnie; znacznikiem czasu pomiaru pozostaje moment odbioru (ts=now).
    """
    global _last_tristar_ts
    ts = time.time()
    try:
        records = await tristar.fetch(ts=ts)
    except Exception as exc:  # noqa: BLE001
        logger.warning("TRISTAR polling blad: %s", exc)
        return
    for rec in records:
        storage.insert_measurement(rec)
    _last_tristar_ts = ts
    logger.info("TRISTAR: zapisano %d pomiarow", len(records))


async def poll_zditm() -> None:
    """Pobiera pozycje pojazdow ZDiTM (Szczecin) i zapisuje proxy ruchu jako 'zditm'.

    Niezalezne od TomTom/TRISTAR - wlasny interwal, wlasna obsluga bledow.
    """
    global _last_zditm_ts
    ts = time.time()
    try:
        records = await zditm.fetch(ts=ts)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ZDiTM polling blad: %s", exc)
        return
    for rec in records:
        storage.insert_measurement(rec)
    _last_zditm_ts = ts
    logger.info("ZDiTM: zapisano %d pomiarow", len(records))


async def poll_portcalls() -> None:
    """Odswieza cache zywych zawiniec statkow (UM Gdynia) dla skladnika PresjaPortu CPI."""
    try:
        n = await portcalls_live.refresh()
    except Exception as exc:  # noqa: BLE001
        logger.warning("PortCalls live blad: %s", exc)
        return
    logger.info("PortCalls live: %d statkow w cache", n)


async def poll_once() -> None:
    """Jeden pelny cykl pollingu (flow + incydenty) + odswiezenie raportow LLM."""
    global _last_poll_ts
    await asyncio.gather(_poll_flows(), _poll_incidents())
    storage.purge_older_than(max_age_seconds=settings.measurement_retention_seconds)
    _last_poll_ts = time.time()
    try:
        from . import reports

        await reports.refresh_reports()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Odswiezenie raportow nieudane: %s", exc)
    logger.info("Polling zakonczony o %s", _last_poll_ts)


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        poll_once,
        "interval",
        seconds=settings.poll_interval_seconds,
        id="tomtom_poll",
        max_instances=1,
        coalesce=True,
    )
    # Job TRISTAR - osobny interwal, startuje od razu by mapa nie czekala 5 min.
    _scheduler.add_job(
        poll_tristar,
        "interval",
        seconds=settings.tristar_poll_interval_seconds,
        id="tristar_poll",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(),
    )
    # Job ZDiTM - osobny interwal (co 30 s), startuje od razu.
    _scheduler.add_job(
        poll_zditm,
        "interval",
        seconds=settings.zditm_poll_interval_seconds,
        id="zditm_poll",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(),
    )
    # Job zywych zawiniec statkow (UM Gdynia) - co 30 min, startuje od razu.
    _scheduler.add_job(
        poll_portcalls,
        "interval",
        seconds=settings.portcalls_poll_interval_seconds,
        id="portcalls_poll",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(),
    )
    _scheduler.start()
    logger.info("Scheduler wystartowal (co %s s)", settings.poll_interval_seconds)
    return _scheduler


async def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
    if _client is not None:
        await _client.aclose()
