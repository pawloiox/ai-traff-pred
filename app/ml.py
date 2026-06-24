"""Modul uczenia maszynowego (XGBoost) do przewidywania kongestii."""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from .config import settings
from . import portdata

try:
    import xgboost as xgb
except ImportError:
    xgb = None

logger = logging.getLogger("port_traffic_pulse.ml")

MODEL_PATH = "xgboost_model.json"

# Przechowujemy model w pamieci by nie ladowac go z dysku co chwile
_GLOBAL_MODEL: Optional[xgb.XGBRegressor] = None
_IS_TRAINING = False

# Mapowanie point_id -> indeks numeryczny (budowane przy treningu, utrwalane)
_POINT_ID_MAP: Dict[str, int] = {}
_POINT_MAP_PATH = "point_id_map.json"


def _load_point_map():
    """Wczytuje mapowanie point_id -> int z dysku."""
    global _POINT_ID_MAP
    import json, os
    if os.path.exists(_POINT_MAP_PATH):
        try:
            with open(_POINT_MAP_PATH, "r") as f:
                _POINT_ID_MAP = json.load(f)
            logger.info("Zaladowano mapowanie point_id (%d punktow)", len(_POINT_ID_MAP))
        except Exception as e:
            logger.error("Blad wczytywania mapy punktow: %s", e)


def _save_point_map():
    """Zapisuje mapowanie point_id -> int na dysk."""
    import json
    with open(_POINT_MAP_PATH, "w") as f:
        json.dump(_POINT_ID_MAP, f)


def point_id_to_idx(point_id: str) -> int:
    """Zwraca indeks numeryczny dla point_id; -1 jesli nieznany."""
    return _POINT_ID_MAP.get(point_id, -1)


def load_model():
    """Wczytuje pre-trenowany model z dysku (jesli istnieje)."""
    global _GLOBAL_MODEL
    if xgb is None:
        return
    import os
    _load_point_map()
    if os.path.exists(MODEL_PATH):
        try:
            model = xgb.XGBRegressor()
            model.load_model(MODEL_PATH)
            _GLOBAL_MODEL = model
            logger.info("Zaladowano pre-trenowany model z %s", MODEL_PATH)
        except Exception as e:
            logger.error("Blad wczytywania modelu z %s: %s", MODEL_PATH, e)


def build_training_dataset(db_path: str = "traffic.db") -> Tuple[pd.DataFrame, pd.Series]:
    """Buduje zestaw danych treningowych dla XGBoost.

    Pobiera dane z `measurements` i probkuje przód o 1 do 12 godzin by stworzyc
    target `future_ratio`.
    Zwraca (X, y) jako pandas DataFrame i Series.
    """
    global _POINT_ID_MAP

    logger.info("Budowanie zestawu danych treningowych...")
    with sqlite3.connect(db_path) as conn:
        # Pobieramy podstawowe pomiary z tomtom
        query = """
            SELECT
                point_id,
                port_id,
                ts,
                congestion_ratio,
                CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INTEGER) AS hour,
                CAST(strftime('%w', ts, 'unixepoch', 'localtime') AS INTEGER) AS dow_sqlite
            FROM measurements
            WHERE source = 'tomtom' AND congestion_ratio IS NOT NULL
            ORDER BY point_id, ts ASC
        """
        df = pd.read_sql_query(query, conn)

    if df.empty:
        return pd.DataFrame(), pd.Series()

    # Budujemy stabilne mapowanie point_id -> int (zachowujemy kolejnosc)
    unique_points = sorted(df["point_id"].unique())
    _POINT_ID_MAP = {pid: idx for idx, pid in enumerate(unique_points)}
    _save_point_map()
    logger.info("Zbudowano mapowanie point_id: %s", _POINT_ID_MAP)

    # Dodajemy kolumne point_idx
    df["point_idx"] = df["point_id"].map(_POINT_ID_MAP)

    # Zamiana dow_sqlite (0=Niedziela) na day_of_week (0=Poniedzialek)
    df["day_of_week"] = df["dow_sqlite"].replace({0: 6, 1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5})
    df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)

    # Niestety nie mamy historycznej pogody per punkt-czas w 1 zapytaniu, 
    # wiec zastosujemy uproszczenie lub pobierzemy najblizszy weather_penalty z weather_cache.
    # By to dzialalo szybko w Pandas:
    with sqlite3.connect(db_path) as conn:
        df_weather = pd.read_sql_query("SELECT ts, port_id, weather_penalty FROM weather_cache", conn)
        
    if not df_weather.empty:
        # Sort values for merge_asof
        df = df.sort_values("ts")
        df_weather = df_weather.sort_values("ts")
        # Dolaczamy pogode uzywajac najblizszego czasu w przeszlosci (asof merge)
        # ale musimy iterowac po portach, bo merge_asof wymaga kluczy by (port_id)
        frames = []
        for port_id, group in df.groupby("port_id"):
            w_group = df_weather[df_weather["port_id"] == port_id]
            if w_group.empty:
                group["weather_penalty"] = 0.0
                frames.append(group)
                continue
            merged = pd.merge_asof(group, w_group[["ts", "weather_penalty"]], on="ts", direction="backward")
            frames.append(merged)
        df = pd.concat(frames).sort_values(["point_id", "ts"])
    else:
        df["weather_penalty"] = 0.0

    df["weather_penalty"] = df["weather_penalty"].fillna(0.0)

    # Budujemy presje portu na bieżący timestamp dla każdego wiersza.
    # W duzym systemie zrobilibysmy to przez wektoryzacje. Tutaj, by nie blokowac
    # za dlugo pamieci, uzyjemy prostego mapowania (zakladajac ze presja portu nie zmienia
    # sie tak dramatycznie co minute - mozna cache'owac).
    # Dla uproszczenia MVP w XGBoost zignorujemy presje portu w treningu,
    # albo wstawimy 0.0. Uczymy sie glownie wzorcow czasowych i pogodowych.
    df["port_pressure"] = 0.0

    # Tworzenie horyzontow (1, 3, 6, 12h)
    X_list = []
    y_list = []
    
    # Sortujemy by moc iterowac wydajnie
    df = df.sort_values(["point_id", "ts"])
    
    # Tolerancja dla znalezienia przyszlej probki to np. +/- 15 minut
    tolerance = 15 * 60

    for horizon_hours in [1, 2, 3, 6, 12]:
        horizon_sec = horizon_hours * 3600
        # Przesunieta ramka (szukamy przyszlosci)
        future_df = df[["point_id", "ts", "congestion_ratio"]].copy()
        future_df["ts"] = future_df["ts"] - horizon_sec
        future_df = future_df.rename(columns={"congestion_ratio": "future_ratio"})
        
        # Laczymy (asof na najblizsza probke)
        # Robimy merge_asof per point_id
        merged_frames = []
        for point_id in df["point_id"].unique():
            curr = df[df["point_id"] == point_id]
            fut = future_df[future_df["point_id"] == point_id]
            if fut.empty:
                continue
            # Chcemy by do obecnego ts dolaczyc "przyszle" ts - horizon.
            # Uzywamy nearest z tolerancja
            m = pd.merge_asof(
                curr, fut[["ts", "future_ratio"]], 
                on="ts", 
                direction="nearest", 
                tolerance=tolerance
            )
            merged_frames.append(m)
            
        if not merged_frames:
            continue
            
        merged = pd.concat(merged_frames)
        # Odrzucamy wiersze bez przyszlej wartosci
        merged = merged.dropna(subset=["future_ratio"])
        
        if merged.empty:
            continue
            
        merged["horizon_hours"] = horizon_hours
        
        features = merged[[
            "point_idx", "hour", "day_of_week", "is_weekend", 
            "weather_penalty", "port_pressure", 
            "congestion_ratio", "horizon_hours"
        ]]
        target = merged["future_ratio"]
        
        X_list.append(features)
        y_list.append(target)

    if not X_list:
        logger.warning("Nie udalo sie zbudowac targetow do trenowania (za malo danych historycznych).")
        return pd.DataFrame(), pd.Series()

    X = pd.concat(X_list, ignore_index=True)
    y = pd.concat(y_list, ignore_index=True)
    
    logger.info("Zbudowano %d probek treningowych.", len(X))
    return X, y


def train_model() -> Dict[str, Any]:
    """Trenuje model XGBoost i zapisuje go w pamieci (_GLOBAL_MODEL)."""
    global _GLOBAL_MODEL, _IS_TRAINING
    
    if xgb is None:
        return {"status": "error", "message": "XGBoost nie jest zainstalowany."}
        
    if _IS_TRAINING:
        return {"status": "error", "message": "Trenowanie jest juz w toku."}
        
    _IS_TRAINING = True
    start_t = time.time()
    try:
        X, y = build_training_dataset()
        if len(X) < 100:
            return {
                "status": "error", 
                "message": f"Zbyt malo danych do trenowania (wymagane 100, jest {len(X)})."
            }
            
        # Model Parameters
        model = xgb.XGBRegressor(
            n_estimators=200,
            learning_rate=0.08,
            max_depth=6,
            objective="reg:squarederror",
            n_jobs=-1,
            random_state=42,
            enable_categorical=False,
        )
        
        model.fit(X, y)
        _GLOBAL_MODEL = model
        
        # Zapis do dysku, by model byl "pre-trained" miedzy restartami
        model.save_model(MODEL_PATH)
        logger.info("Zapisano przetrenowany model do %s", MODEL_PATH)
        
        elapsed = time.time() - start_t
        logger.info("Model przetrenowany pomyslnie w %.2f sekund.", elapsed)
        return {
            "status": "ok", 
            "samples": len(X), 
            "elapsed_seconds": round(elapsed, 2)
        }
    except Exception as e:
        logger.error("Blad trenowania XGBoost: %s", e)
        return {"status": "error", "message": str(e)}
    finally:
        _IS_TRAINING = False


def is_model_ready() -> bool:
    return _GLOBAL_MODEL is not None


def predict_horizon(
    current_ratio: float,
    weather_penalty: float,
    port_pressure: float,
    horizon_hours: int,
    point_id: str = "",
) -> float:
    """Zwraca predykcje z modelu XGBoost. Zglasza ValueError jesli model nie gotowy."""
    if _GLOBAL_MODEL is None:
        raise ValueError("Model nie jest wytrenowany")

    from datetime import datetime
    dt = datetime.now()
    hour = dt.hour
    dow = dt.weekday()
    is_weekend = 1 if dow >= 5 else 0

    p_idx = point_id_to_idx(point_id)

    features = pd.DataFrame([{
        "point_idx": p_idx,
        "hour": hour,
        "day_of_week": dow,
        "is_weekend": is_weekend,
        "weather_penalty": weather_penalty,
        "port_pressure": port_pressure,
        "congestion_ratio": current_ratio,
        "horizon_hours": horizon_hours
    }])

    pred = float(_GLOBAL_MODEL.predict(features)[0])
    # Zabezpieczenie wynikow do [0.0, 1.0]
    return max(0.0, min(1.0, pred))

# Proba wczytania modelu przy imporcie modulu
load_model()
