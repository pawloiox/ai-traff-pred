"""Generator realistycznej historii pomiarow do treningu modelu ML.

Kazdy punkt pomiarowy ma unikalna charakterystyke kongestii, odzwierciedlajaca
realne warunki na polskich drogach portowych:
- Trasa Sucharskiego / Estakada Kwiatkowskiego: glowne arterie z duzym ruchem
- Tunel pod Martwa Wisla: waskie gardlo z ostrymi szczytami
- Ulice miejskie: umiarkowany ruch z wyraznym szczytem porannym/popoludniowym
- Drogi ekspresowe (S3): mniejsza kongestia ale wrazliwosc na pogode
"""

import os
import sqlite3
import random
import time
import math
from datetime import datetime, timedelta

from app.ports import PORTS, all_points
from app.weather import _compute_weather_penalty
from app.ml import train_model

# ============================================================
# Per-point congestion profiles
# ============================================================
# Slownik: point_id -> dict z parametrami
#   base:       bazowy poziom kongestii (noc, brak ruchu)
#   am_peak:    dodatkowy wzrost w szczycie porannym (7-9)
#   pm_peak:    dodatkowy wzrost w szczycie popoludniowym (15-17)
#   midday:     dodatkowy wzrost w srodku dnia (10-14)
#   weekend:    dodatkowy wzrost w weekend (11-15)
#   noise:      amplituda szumu losowego
#   incident_p: prawdopodobienstwo incydentu (per 10-min slot)
#   weather_k:  mnoznik wplywu pogody na zator

POINT_PROFILES = {
    # === Port Gdansk ===
    "gda_sucharskiego": {
        "base": 0.12, "am_peak": 0.35, "pm_peak": 0.45, "midday": 0.18,
        "weekend": 0.08, "noise": 0.06, "incident_p": 0.03, "weather_k": 1.8,
    },
    "gda_marynarki_polskiej": {
        "base": 0.10, "am_peak": 0.28, "pm_peak": 0.38, "midday": 0.15,
        "weekend": 0.06, "noise": 0.05, "incident_p": 0.02, "weather_k": 1.4,
    },
    "gda_tunel": {
        "base": 0.15, "am_peak": 0.40, "pm_peak": 0.50, "midday": 0.22,
        "weekend": 0.10, "noise": 0.08, "incident_p": 0.04, "weather_k": 2.0,
    },
    "gda_dct": {
        "base": 0.08, "am_peak": 0.22, "pm_peak": 0.30, "midday": 0.12,
        "weekend": 0.04, "noise": 0.04, "incident_p": 0.015, "weather_k": 1.2,
    },
    "gda_ku_ujsciu": {
        "base": 0.06, "am_peak": 0.18, "pm_peak": 0.25, "midday": 0.10,
        "weekend": 0.03, "noise": 0.03, "incident_p": 0.01, "weather_k": 1.0,
    },
    "gda_elblaska": {
        "base": 0.11, "am_peak": 0.32, "pm_peak": 0.42, "midday": 0.16,
        "weekend": 0.07, "noise": 0.05, "incident_p": 0.025, "weather_k": 1.6,
    },
    # === Port Gdynia ===
    "gdy_kwiatkowskiego": {
        "base": 0.13, "am_peak": 0.38, "pm_peak": 0.48, "midday": 0.20,
        "weekend": 0.09, "noise": 0.07, "incident_p": 0.03, "weather_k": 1.7,
    },
    "gdy_wisniewskiego": {
        "base": 0.10, "am_peak": 0.30, "pm_peak": 0.40, "midday": 0.16,
        "weekend": 0.06, "noise": 0.05, "incident_p": 0.02, "weather_k": 1.5,
    },
    "gdy_polska": {
        "base": 0.09, "am_peak": 0.25, "pm_peak": 0.35, "midday": 0.14,
        "weekend": 0.05, "noise": 0.04, "incident_p": 0.02, "weather_k": 1.3,
    },
    "gdy_energetykow": {
        "base": 0.07, "am_peak": 0.20, "pm_peak": 0.28, "midday": 0.11,
        "weekend": 0.04, "noise": 0.04, "incident_p": 0.015, "weather_k": 1.1,
    },
    "gdy_morska": {
        "base": 0.11, "am_peak": 0.33, "pm_peak": 0.43, "midday": 0.17,
        "weekend": 0.07, "noise": 0.06, "incident_p": 0.025, "weather_k": 1.5,
    },
    "gdy_wendy": {
        "base": 0.06, "am_peak": 0.15, "pm_peak": 0.22, "midday": 0.09,
        "weekend": 0.03, "noise": 0.03, "incident_p": 0.01, "weather_k": 1.0,
    },
    # === Port Szczecin-Swinoujscie ===
    "szcz_swin_s3": {
        "base": 0.05, "am_peak": 0.15, "pm_peak": 0.20, "midday": 0.08,
        "weekend": 0.04, "noise": 0.03, "incident_p": 0.01, "weather_k": 2.2,
    },
    "szcz_gdanska": {
        "base": 0.12, "am_peak": 0.34, "pm_peak": 0.44, "midday": 0.18,
        "weekend": 0.08, "noise": 0.06, "incident_p": 0.025, "weather_k": 1.6,
    },
    "swin_finska": {
        "base": 0.08, "am_peak": 0.22, "pm_peak": 0.30, "midday": 0.12,
        "weekend": 0.05, "noise": 0.04, "incident_p": 0.015, "weather_k": 1.3,
    },
    "swin_promowy": {
        "base": 0.07, "am_peak": 0.18, "pm_peak": 0.26, "midday": 0.10,
        "weekend": 0.12, "noise": 0.05, "incident_p": 0.02, "weather_k": 1.8,
    },
    "szcz_bytomska": {
        "base": 0.09, "am_peak": 0.26, "pm_peak": 0.36, "midday": 0.14,
        "weekend": 0.05, "noise": 0.04, "incident_p": 0.02, "weather_k": 1.4,
    },
    "szcz_struga": {
        "base": 0.10, "am_peak": 0.30, "pm_peak": 0.40, "midday": 0.16,
        "weekend": 0.06, "noise": 0.05, "incident_p": 0.02, "weather_k": 1.5,
    },
}

# Predkosc free-flow per punkt (realistyczne wartosci)
FREE_FLOW_SPEEDS = {
    "gda_sucharskiego": 70.0,
    "gda_marynarki_polskiej": 50.0,
    "gda_tunel": 60.0,
    "gda_dct": 40.0,
    "gda_ku_ujsciu": 40.0,
    "gda_elblaska": 50.0,
    "gdy_kwiatkowskiego": 70.0,
    "gdy_wisniewskiego": 50.0,
    "gdy_polska": 50.0,
    "gdy_energetykow": 40.0,
    "gdy_morska": 60.0,
    "gdy_wendy": 40.0,
    "szcz_swin_s3": 120.0,
    "szcz_gdanska": 50.0,
    "swin_finska": 50.0,
    "swin_promowy": 50.0,
    "szcz_bytomska": 50.0,
    "szcz_struga": 60.0,
}


def _smooth_peak(hour: int, center: int, width: float = 1.5) -> float:
    """Gaussowski ksztalt szczytu ruchu.
    
    Daje gladkie przejscie zamiast skokowych przedzialow (np. 7-9), 
    co sprawia ze model uczy sie plynnych trendow.
    """
    return math.exp(-0.5 * ((hour - center) / width) ** 2)


def _compute_congestion(
    profile: dict,
    hour: int,
    dow: int,
    is_weekend: bool,
    weather_penalty: float,
) -> float:
    """Oblicza realistyczny congestion_ratio dla danego punktu i momentu."""
    
    ratio = profile["base"]
    
    if not is_weekend:
        # Szczyt poranny (centrum ~8:00)
        ratio += profile["am_peak"] * _smooth_peak(hour, 8, 1.5)
        # Szczyt popoludniowy (centrum ~16:30, nieco szerszy)
        ratio += profile["pm_peak"] * _smooth_peak(hour, 16.5, 1.8)
        # Srodek dnia (lekki wzrost 10-14)
        ratio += profile["midday"] * _smooth_peak(hour, 12, 2.5)
    else:
        # Weekend: lagodniejszy wzrost w srodku dnia
        ratio += profile["weekend"] * _smooth_peak(hour, 13, 3.0)
    
    # Wplyw pogody (skalowany per punkt)
    ratio += weather_penalty * profile["weather_k"]
    
    # Losowy szum (symulacja naturalnej zmiennosci)
    ratio += random.gauss(0, profile["noise"])
    
    # Losowe incydenty (wypadki, roboty drogowe)
    if random.random() < profile["incident_p"]:
        ratio += random.uniform(0.25, 0.55)
    
    return max(0.0, min(1.0, ratio))


def generate_history(days: int = 30):
    db_path = "traffic.db"
    now = datetime.now()
    start_time = now - timedelta(days=days)

    print(f"Rozpoczynam generowanie danych od {start_time} do {now}...")

    # Przygotowanie polaczenia bazy
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS weather_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            port_id TEXT,
            temperature REAL,
            rain REAL,
            wind_speed REAL,
            visibility REAL,
            weather_code INTEGER,
            weather_penalty REAL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_measurements_point_ts ON measurements(point_id, ts)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_weather_port_ts ON weather_cache(port_id, ts)")
    
    # 1. Usun stare wygenerowane dane z tego zakresu by zapobiec duplikatom
    start_ts = start_time.timestamp()
    end_ts = now.timestamp()
    cursor.execute("DELETE FROM measurements WHERE ts >= ? AND ts <= ?", (start_ts, end_ts))
    cursor.execute("DELETE FROM weather_cache WHERE ts >= ? AND ts <= ?", (start_ts, end_ts))

    measurements_data = []
    weather_data = []

    # Bedziemy skakac co 10 minut
    current_time = start_time
    delta = timedelta(minutes=10)

    points = all_points()
    
    # Utrwalamy seed na pogode by byla spatialnie korelowana (ten sam dzien = ta sama pogoda)
    weather_seed_base = int(start_ts) // 86400

    while current_time < now:
        ts = current_time.timestamp()
        hour = current_time.hour + current_time.minute / 60.0  # ulamkowa godzina
        hour_int = current_time.hour
        dow = current_time.weekday()
        is_weekend = dow >= 5
        day_seed = int(ts) // 86400  # ten sam seed na caly dzien

        # Generowanie pogody dla kazdego portu
        port_weather = {}
        for port in PORTS:
            # Pogoda korelowana w czasie (ten sam dzien ~ podobna pogoda)
            rng = random.Random(day_seed * 1000 + hash(port.id) % 1000 + hour_int)
            is_raining = rng.random() < 0.15
            rain = rng.uniform(0.5, 5.0) if is_raining else 0.0
            temp = rng.uniform(5.0, 25.0)
            wind = rng.uniform(1.0, 15.0)
            vis = rng.uniform(1000.0, 5000.0) if is_raining else rng.uniform(10000.0, 40000.0)
            code = 61 if is_raining else 0
            
            penalty = _compute_weather_penalty(rain, wind, vis, code)
            port_weather[port.id] = penalty
            
            # Dodajemy pogode raz na godzine
            if current_time.minute < 10:
                weather_data.append((
                    ts, port.id, temp, rain, wind, vis, code, penalty
                ))

        # Generowanie pomiarow dla kazdego punktu
        for port, pt in points:
            profile = POINT_PROFILES.get(pt.id)
            if profile is None:
                continue
            
            w_penalty = port_weather.get(port.id, 0.0)
            final_ratio = _compute_congestion(profile, hour, dow, is_weekend, w_penalty)
            
            ffs = FREE_FLOW_SPEEDS.get(pt.id, 50.0)
            current_speed = max(5.0, ffs * (1.0 - final_ratio))
            
            measurements_data.append((
                ts, port.id, pt.id, pt.name, pt.road, pt.lat, pt.lon,
                current_speed, ffs, final_ratio, 1.0, 0, "tomtom", "measured", 0.0
            ))
            
            # Syntetyczne proxy ZDiTM dla Szczecina co 30 min
            if port.id == "szczecin_swinoujscie" and current_time.minute % 30 == 0:
                zditm_ratio = max(0.0, min(1.0, final_ratio + random.gauss(0, 0.03)))
                measurements_data.append((
                    ts, port.id, pt.id, pt.name, pt.road, pt.lat, pt.lon,
                    current_speed, ffs, zditm_ratio, 1.0, 0, "zditm", "measured", 0.0
                ))

        current_time += delta

    print(f"Wstawianie {len(measurements_data)} rekordow pomiarow...")
    cursor.executemany("""
        INSERT INTO measurements (
            ts, port_id, point_id, point_name, road, lat, lon,
            current_speed, free_flow_speed, congestion_ratio, confidence, road_closure, source, confidence_label, intensity
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, measurements_data)
    
    print(f"Wstawianie {len(weather_data)} rekordow pogody...")
    cursor.executemany("""
        INSERT INTO weather_cache (ts, port_id, temperature, rain, wind_speed, visibility, weather_code, weather_penalty)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, weather_data)

    conn.commit()
    conn.close()
    
    print("Dane wygenerowane i zapisane. Rozpoczynam trening modelu...")
    res = train_model()
    print("Trening zakonczony:", res)

if __name__ == "__main__":
    generate_history(30)
