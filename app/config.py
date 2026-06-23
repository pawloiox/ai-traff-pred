"""Konfiguracja aplikacji: klucz TomTom, parametry pollingu i progi analityczne."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    tomtom_api_key: str
    poll_interval_seconds: int
    db_path: str

    # Interwaly pollingu nowych zrodel (sekundy). Osobne od joba TomTom.
    tristar_poll_interval_seconds: int = 300  # TRISTAR co 5 min

    # Groq (LLM) - generacja narracji raportow operacyjnych.
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"
    groq_enabled: bool = True
    groq_timeout: float = 20.0

    # Progi congestion ratio (1 - currentSpeed/freeFlowSpeed).
    ratio_warning: float = 0.30   # zwolnienie - uwaga
    ratio_critical: float = 0.55  # silny zator

    # Okno (minuty) do rankingu waskich gardel.
    bottleneck_window_minutes: int = 60

    # Detekcja anomalii.
    anomaly_min_samples: int = 12        # minimalna liczba probek dla baseline
    anomaly_zscore_threshold: float = 2.5

    # Predykcja trendu.
    prediction_window_minutes: int = 30  # okno historii do regresji
    prediction_horizon_minutes: int = 20  # horyzont prognozy
    prediction_rising_slope: float = 0.05  # min. przyrost ratio / 10 min uznany za narastanie

    # Promien (metry) korelacji incydentu z punktem przy raportach.
    incident_link_radius_m: float = 1500.0


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "tak"}


def load_settings() -> Settings:
    tomtom_key = os.getenv("TOMTOM_API_KEY", "")
    if not tomtom_key:
        raise RuntimeError(
            "Brak TOMTOM_API_KEY. Skopiuj .env.example do .env i ustaw swoj klucz."
        )
    groq_key = os.getenv("GROQ_API_KEY", "")
    groq_enabled = _get_bool("GROQ_ENABLED", True)
    if groq_enabled and not groq_key:
        groq_enabled = False

    return Settings(
        tomtom_api_key=tomtom_key,
        poll_interval_seconds=_get_int("POLL_INTERVAL_SECONDS", 60),
        tristar_poll_interval_seconds=_get_int("TRISTAR_POLL_INTERVAL_SECONDS", 300),
        db_path=os.getenv("DB_PATH", "traffic.db"),
        groq_api_key=groq_key,
        groq_model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
        groq_enabled=groq_enabled,
    )


settings = load_settings()

