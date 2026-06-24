"""Cechy temporalne: kalendarz swiat PL, godziny szczytu, weekendy.

Modul dostarcza funkcje `temporal_features(dt)` zwracajaca slownik cech
temporalnych dla dowolnego momentu czasu - wykorzystywany przez silnik
scoringu delay_risk_score (analysis.py) oraz analityke firmowa.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional


# --- Polskie dni wolne ustawowo (2025-2027) ---
# Stale (powtarzalne co roku):
_FIXED_HOLIDAYS = {
    (1, 1),    # Nowy Rok
    (1, 6),    # Trzech Kroli
    (5, 1),    # Swieto Pracy
    (5, 3),    # Swieto Konstytucji 3 Maja
    (8, 15),   # Wniebowziecie NMP
    (11, 1),   # Wszystkich Swietych
    (11, 11),  # Swieto Niepodleglosci
    (12, 25),  # Boze Narodzenie
    (12, 26),  # Drugi dzien Bozego Narodzenia
}


def _easter(year: int) -> date:
    """Algorytm Gaussa - data Wielkanocy dla danego roku."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _movable_holidays(year: int) -> set[date]:
    """Ruchome swieta polskie zależne od daty Wielkanocy."""
    e = _easter(year)
    return {
        e,                              # Wielkanoc (niedziela)
        e + timedelta(days=1),          # Poniedzialek Wielkanocny
        e + timedelta(days=49),         # Zeslanie Ducha Swietego (Zielone Swiatki)
        e + timedelta(days=60),         # Boze Cialo
    }


def is_holiday(d: date) -> bool:
    """Sprawdza czy podana data to polski dzien wolny ustawowo."""
    if (d.month, d.day) in _FIXED_HOLIDAYS:
        return True
    return d in _movable_holidays(d.year)


def temporal_features(dt: Optional[datetime] = None) -> Dict[str, Any]:
    """Zwraca slownik cech temporalnych dla danego momentu.

    Cechy:
        is_rush_hour: bool - czy godzina szczytu (6-9, 15-18 w dni robocze)
        is_weekend: bool - sobota lub niedziela
        is_holiday: bool - polski dzien wolny ustawowo
        is_workday: bool - dzien roboczy (nie weekend, nie swieto)
        day_of_week: int - 0=pn, 6=nd
        hour: int - godzina (0-23)
        temporal_peak_penalty: float - kara temporalna [0.0 - 1.0]
    """
    if dt is None:
        dt = datetime.now()

    d = dt.date()
    hour = dt.hour
    dow = dt.weekday()  # 0=pn, 6=nd
    weekend = dow >= 5
    holiday = is_holiday(d)
    workday = not weekend and not holiday

    # Godziny szczytu: 6:00-9:00 i 15:00-18:00 (tylko w dni robocze)
    rush_hour = workday and (6 <= hour <= 8 or 15 <= hour <= 17)

    # --- temporal_peak_penalty ---
    # Bazowa kara godzinowa (profil dobowy dla dnia roboczego):
    # Szczyty poranne i popoludniowe mają wyzsze kary.
    _HOURLY_PROFILE = {
        0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0, 4: 0.05, 5: 0.1,
        6: 0.6, 7: 0.9, 8: 0.8, 9: 0.5, 10: 0.3, 11: 0.25,
        12: 0.3, 13: 0.25, 14: 0.35, 15: 0.75, 16: 0.95, 17: 0.85,
        18: 0.5, 19: 0.3, 20: 0.15, 21: 0.1, 22: 0.05, 23: 0.0,
    }

    base_penalty = _HOURLY_PROFILE.get(hour, 0.0)

    if holiday:
        # Swieta: ruch znacznie nizszy
        penalty = base_penalty * 0.2
    elif weekend:
        # Weekendy: ruch nizszy niz w dni robocze, ale wyższy niż w święta
        if dow == 5:  # sobota
            penalty = base_penalty * 0.4
        else:  # niedziela
            penalty = base_penalty * 0.25
    else:
        penalty = base_penalty

    return {
        "is_rush_hour": rush_hour,
        "is_weekend": weekend,
        "is_holiday": holiday,
        "is_workday": workday,
        "day_of_week": dow,
        "hour": hour,
        "temporal_peak_penalty": round(min(1.0, max(0.0, penalty)), 3),
    }
