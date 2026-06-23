"""FastAPI: REST API + serwowanie frontu (Leaflet) + start schedulera pollingu."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import analysis, reports, scheduler
from .ports import PORTS
from .tomtom import TomTomClient

logging.basicConfig(level=logging.INFO)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start_scheduler()
    # Pierwszy polling od razu, by mapa nie byla pusta.
    asyncio.create_task(scheduler.poll_once())
    yield
    await scheduler.shutdown()


app = FastAPI(title="Port Traffic Pulse", version="0.1.0", lifespan=lifespan)

_tile_client = TomTomClient()


@app.get("/api/ports")
def api_ports():
    return {
        "ports": [
            {
                "id": p.id,
                "name": p.name,
                "center": {"lat": p.center[0], "lon": p.center[1]},
                "zoom": p.zoom,
                "bbox": p.bbox,
                "points": [
                    {
                        "id": pt.id,
                        "name": pt.name,
                        "lat": pt.lat,
                        "lon": pt.lon,
                        "road": pt.road,
                    }
                    for pt in p.points
                ],
            }
            for p in PORTS
        ],
        "tiles": {
            "basemap": _tile_client.basemap_tile_url(),
            "flow": _tile_client.flow_tile_url(),
            "incidents": _tile_client.incidents_tile_url(),
        },
    }


@app.get("/api/status")
def api_status():
    return {
        "last_poll": scheduler.last_poll_ts(),
        "points": analysis.current_status(),
    }


@app.get("/api/bottlenecks")
def api_bottlenecks(window: int = Query(60, ge=5, le=720), limit: int = Query(10, ge=1, le=50)):
    return {"window_minutes": window, "bottlenecks": analysis.bottlenecks(window, limit)}


@app.get("/api/incidents")
def api_incidents(port: Optional[str] = None):
    from .storage import storage

    return {"incidents": storage.current_incidents(port)}


@app.get("/api/anomalies")
def api_anomalies():
    return {"anomalies": analysis.detect_anomalies()}


@app.get("/api/predictions")
def api_predictions():
    return {"predictions": analysis.predict_trends()}


@app.get("/api/reports")
def api_reports(limit: int = Query(8, ge=1, le=50)):
    return {
        "generated_at": reports.cache_timestamp(),
        "reports": reports.get_cached_reports(limit),
    }


@app.get("/api/tristar")
def api_tristar():
    """Surowe, najnowsze pomiary warstwy TRISTAR (Gdynia) - intensywnosc poj/h."""
    from .storage import storage

    return {
        "last_poll": scheduler.last_tristar_ts(),
        "measurements": storage.latest_measurements(source="tristar"),
    }


@app.get("/api/cpi")
def api_cpi(point_id: str = Query(...), horizon: float = Query(1.0, ge=1, le=6)):
    """Indeks Presji Zatorowej z rozkladem na 4 skladniki dla punktu i horyzontu (h)."""
    from . import cpi

    return cpi.compute_cpi(point_id, horizon)


@app.get("/api/cpi/all")
def api_cpi_all(horizon: float = Query(1.0, ge=1, le=6)):
    """CPI z rozkladem dla wszystkich monitorowanych punktow (kolorowanie mapy wg horyzontu)."""
    from . import cpi
    from .ports import all_points

    points = []
    for port, point in all_points():
        result = cpi.compute_cpi(point.id, horizon)
        points.append({**result, "point_name": point.name, "port_id": port.id,
                       "lat": point.lat, "lon": point.lon, "road": point.road})
    return {"horizon": horizon, "points": points}


@app.get("/api/zditm")
def api_zditm():
    """Surowe, najnowsze pomiary warstwy ZDiTM (Szczecin) - proxy z predkosci GPS."""
    from .storage import storage

    return {
        "last_poll": scheduler.last_zditm_ts(),
        "measurements": storage.latest_measurements(source="zditm"),
    }


@app.post("/api/refresh")
async def api_refresh():
    await scheduler.poll_once()
    return {"status": "ok", "last_poll": scheduler.last_poll_ts()}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
