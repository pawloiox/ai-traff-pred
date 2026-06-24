import os
import sqlite3
import random
import time
from datetime import datetime, timedelta

from app.ports import PORTS, all_points
from app.weather import _compute_weather_penalty
from app.ml import train_model

def generate_history(days: int = 30):
    db_path = "traffic.db"
    now = datetime.now()
    start_time = now - timedelta(days=days)

    print(f"Rozpoczynam generowanie danych od {start_time} do {now}...")

    # Przygotowanie polaczenia bazy
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Nie tworzymy tabeli recznie, uzyjemy istniejacego schematu.
    # W ten sposob unikniemy konfliktow.

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

    while current_time < now:
        ts = current_time.timestamp()
        hour = current_time.hour
        dow = current_time.weekday()
        is_weekend = dow >= 5

        # Generowanie pogody dla kazdego portu (raz na godzine by nie zapychac cache, ale ok mozemy co 10 min uproszczone)
        port_weather = {}
        for port in PORTS:
            # Losowa pogoda
            is_raining = random.random() < 0.15  # 15% szans na deszcz
            rain = random.uniform(0.5, 5.0) if is_raining else 0.0
            temp = random.uniform(5.0, 25.0)
            wind = random.uniform(1.0, 15.0)
            vis = random.uniform(1000.0, 5000.0) if is_raining else random.uniform(10000.0, 40000.0)
            code = 61 if is_raining else 0
            
            penalty = _compute_weather_penalty(rain, wind, vis, code)
            port_weather[port.id] = penalty
            
            # Dodajemy tylko raz na godzine (np. gdy minuty sa bliskie 0)
            if current_time.minute < 10:
                weather_data.append((
                    ts, port.id, temp, rain, wind, vis, code, penalty
                ))

        # Generowanie pomiarow dla kazdego punktu
        for port, pt in points:
            # Bazowe natezenie ruchu
            base_ratio = random.uniform(0.05, 0.20)
            
            # Wzrost w godzinach szczytu (dni robocze)
            if not is_weekend:
                if 7 <= hour <= 9:  # Poranny szczyt
                    base_ratio += random.uniform(0.2, 0.4)
                elif 15 <= hour <= 17:  # Popoludniowy szczyt
                    base_ratio += random.uniform(0.3, 0.5)
                elif 10 <= hour <= 14:  # Srodek dnia
                    base_ratio += random.uniform(0.1, 0.2)
            else:
                # Delikatny wzrost w weekend w srodku dnia
                if 11 <= hour <= 15:
                    base_ratio += random.uniform(0.05, 0.15)
                    
            # Pogoda podnosi ratio
            w_penalty = port_weather.get(port.id, 0.0)
            base_ratio += w_penalty * 1.5  # Skalowanie wplywu pogody na zator
            
            # Dodatkowy wplyw losowych zatorow incydentalnych
            if random.random() < 0.02:  # 2% szans na wypadek
                base_ratio += random.uniform(0.3, 0.6)

            final_ratio = max(0.0, min(1.0, base_ratio))
            
            # Predkosc jest zalezna odwrotnie proporcjonalnie do ratio
            ffs = 70.0
            current_speed = max(5.0, ffs * (1.0 - final_ratio * 0.8))
            
            measurements_data.append((
                ts, port.id, pt.id, pt.name, pt.road, pt.lat, pt.lon,
                current_speed, ffs, final_ratio, 1.0, 0, "tomtom", "measured", 0.0
            ))
            
            # Dodajemy syntetyczne proxy ZDiTM dla Szczecina co 30 min zeby dzialal fallback
            if port.id == "szczecin_swinoujscie" and current_time.minute % 30 == 0:
                # ZDiTM ma zazwyczaj zblizone ratio
                measurements_data.append((
                    ts, port.id, pt.id, pt.name, pt.road, pt.lat, pt.lon,
                    current_speed, ffs, max(0.0, min(1.0, final_ratio + random.uniform(-0.05, 0.05))), 1.0, 0, "zditm", "measured", 0.0
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
