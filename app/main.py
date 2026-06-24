"""FastAPI: REST API + serwowanie frontu (Leaflet) + start schedulera pollingu."""

from __future__ import annotations

import os
if "NO_PROXY" in os.environ:
    os.environ["NO_PROXY"] = ",".join(p for p in os.environ["NO_PROXY"].split(",") if ":" not in p)

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, Response, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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
            "basemap_light": _tile_client.basemap_tile_url_light(),
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
def api_predictions(horizon: int = Query(1, ge=1, le=12)):
    """Krotkoterminowe predykcje i powiadomienia o zatorach dla wybranego horyzontu (1-12h)."""
    return {"predictions": analysis.predict_trends(horizon_hours=horizon)}


@app.post("/api/ml/train")
def api_ml_train():
    """Wymusza reczne wytrenowanie modelu XGBoost na podstawie historii SQLite."""
    from . import ml
    result = ml.train_model()
    return result


@app.get("/api/reports")
def api_reports(limit: int = Query(8, ge=1, le=50)):
    return {
        "generated_at": reports.cache_timestamp(),
        "reports": reports.get_cached_reports(limit),
    }

@app.get("/api/reports/{point_id}/pdf")
def api_report_pdf(point_id: str):
    from backend.services.reports.pdf_generator import generate_pdf_bytes

    cached = reports.get_cached_reports(limit=50)
    # Szukamy raportu dla tego punktu
    report = next((r for r in cached if r["point_id"] == point_id), None)
    
    if not report:
        raise HTTPException(status_code=404, detail="Raport dla podanego punktu nie istnieje lub wygasl")
        
    pdf_data = generate_pdf_bytes(report)
    return Response(
        content=pdf_data,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=raport_{point_id}.pdf"}
    )


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
    await scheduler.poll_weather()
    return {"status": "ok", "last_poll": scheduler.last_poll_ts()}

class PushSubscription(BaseModel):
    token: str
    role: str = "driver"

@app.post("/api/notifications/subscribe")
def api_subscribe(sub: PushSubscription):
    from .storage import storage
    storage.save_push_subscription(sub.token, sub.role)
    return {"status": "ok", "token_saved": True}



@app.get("/api/risk-scores")
def api_risk_scores():
    """Scoring ryzyka opoznien per punkt (delay_risk_score)."""
    return {"risk_scores": analysis.delay_risk_all()}


@app.get("/api/weather")
def api_weather():
    """Aktualna pogoda per port z Open-Meteo."""
    from .storage import storage

    return {
        "last_poll": scheduler.last_weather_ts(),
        "weather": storage.all_latest_weather(),
    }


@app.get("/api/analytics/congestion-history")
def api_congestion_history(
    point_id: Optional[str] = None,
    days: int = Query(7, ge=1, le=28),
):
    """Godzinowe agregaty kongestii z ostatnich N dni."""
    from .storage import storage

    return {"days": days, "history": storage.congestion_history(point_id, days)}


@app.get("/api/analytics/daily-pattern")
def api_daily_pattern(
    point_id: str = Query(...),
    weeks: int = Query(4, ge=1, le=12),
):
    """Wzorzec tygodniowy: srednia kongestia per godzina i dzien tygodnia."""
    from .storage import storage

    return {"point_id": point_id, "weeks": weeks, "pattern": storage.daily_pattern(point_id, weeks)}


@app.get("/api/analytics/port-summary")
def api_port_summary(
    port_id: Optional[str] = None,
    hours: int = Query(24, ge=1, le=168),
):
    """Podsumowanie kongestii per port."""
    from .storage import storage

    return {"hours": hours, "summary": storage.port_summary(port_id, hours)}


@app.get("/")
def index():
    # Strona tytulowa (wybor roli). Przyciski prowadza do dashboardu.
    return FileResponse(STATIC_DIR / "landing.html")


@app.get("/dyspozytor")
@app.get("/dashboard")
def dashboard():
    # Dotychczasowy dashboard (widok firmy/dyspozytora).
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

