"""Zywe zawiniecia statkow z Urzedu Morskiego w Gdyni (Expected ships).

Oficjalna lista spodziewanych statkow (Gdansk + Gdynia), aktualizowana na biezaco -
zywy odpowiednik historycznego PortCalls. Strona renderuje tabele inline (brak JSON
API), wiec parsujemy HTML przez pandas.read_html. Tabela ma IMO + ETA, ale nie DWT
ani typu statku - te dociagamy ze slownika DspShips po numerze IMO.

Sekcje strony -> terminale:
  "Gdansk Port Polnocny" -> DCT (Deepwater Container Terminal lezy w Porcie Polnocnym)
  "Port Gdynia"          -> BCT/GCT (Gdynia; bez rozbicia na konkretne nabrzeze w zrodle)
  "Gdansk Nowy Port"     -> brak naszych terminali kontenerowych (pomijamy)

Szczecin (DBPS) NIE jest tu dostepny (inny urzad, feed nieaktualny) - DBPS pozostaje
na danych Codeco.
"""

from __future__ import annotations

import io
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import pandas as pd

DATA_DIR = Path(__file__).parent.parent / "data"
EXPECTED_SHIPS_URL = (
    "https://www.umgdy.gov.pl/en/marine-safety/ruch-statkow-en/expected-ships/"
)

# Nagłówek sekcji na stronie -> lista terminali, ktore obsluguje.
SECTION_TERMINALS: Dict[str, List[str]] = {
    "Port Północny": ["DCT"],
    "Port Gdynia": ["BCT", "GCT"],
    # "Nowy Port" -> brak naszych terminali kontenerowych
}


@lru_cache(maxsize=1)
def _imo_dictionary() -> Dict[int, Dict[str, Any]]:
    """IMO -> {dwt, ship_type} ze slownika DspShips (statyczny, wczytywany raz)."""
    dsp = pd.read_excel(DATA_DIR / next(p.name for p in DATA_DIR.glob("DspShips*.xlsx")), header=1)
    dsp["imo"] = pd.to_numeric(dsp["Numer IMO"], errors="coerce")
    dsp["dwt"] = pd.to_numeric(dsp["DWT - nośność statku"], errors="coerce")
    out: Dict[int, Dict[str, Any]] = {}
    for _, r in dsp.dropna(subset=["imo"]).iterrows():
        out[int(r["imo"])] = {
            "dwt": float(r["dwt"]) if pd.notna(r["dwt"]) else None,
            "ship_type": r.get("Typ statku"),
        }
    return out


def _section_for_table_positions(html: str) -> List[str]:
    """Zwraca etykiete sekcji dla kazdej tabeli 'Call ID' w kolejnosci dokumentu.

    Dla kazdej tabeli bierze najblizszy poprzedzajacy ja naglowek h1-h4.
    """
    heads = [(m.start(), re.sub(r"<[^>]+>", "", m.group(1)).strip())
             for m in re.finditer(r"<h[1-4][^>]*>(.*?)</h[1-4]>", html, re.I | re.S)]
    sections: List[str] = []
    for tm in re.finditer(r"<table", html, re.I):
        # tylko tabele zawierajace 'Call ID' (tabele danych)
        chunk = html[tm.start(): tm.start() + 4000]
        if "Call ID" not in chunk:
            continue
        preceding = [h for pos, h in heads if pos < tm.start()]
        sections.append(preceding[-1] if preceding else "")
    return sections


def _terminals_for_section(section: str) -> List[str]:
    for key, terminals in SECTION_TERMINALS.items():
        if key.lower() in section.lower():
            return terminals
    return []


async def fetch(client: Optional[httpx.AsyncClient] = None) -> List[Dict[str, Any]]:
    """Pobiera zywa liste spodziewanych statkow, wzbogacona o DWT/typ i terminale.

    Zwraca rekordy: {ship, imo, eta (datetime tz-aware), section, terminals, dwt, ship_type}.
    Bez zapisu do bazy - dane do skladnika PresjaPortu (KROK E).
    """
    own = client is None
    client = client or httpx.AsyncClient(timeout=25.0)
    try:
        resp = await client.get(
            EXPECTED_SHIPS_URL, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        html = resp.text
    finally:
        if own:
            await client.aclose()

    tables = [t for t in pd.read_html(io.StringIO(html)) if list(t.columns)[:2] == ["Call ID", "Vessel name"]]
    sections = _section_for_table_positions(html)
    imo_dict = _imo_dictionary()

    records: List[Dict[str, Any]] = []
    for table, section in zip(tables, sections):
        terminals = _terminals_for_section(section)
        if not terminals:
            continue  # np. Nowy Port - brak naszych terminali
        for _, row in table.iterrows():
            imo = pd.to_numeric(row.get("IMO"), errors="coerce")
            eta = pd.to_datetime(row.get("ETA (LT)"), errors="coerce", utc=True)
            if pd.isna(eta):
                continue
            info = imo_dict.get(int(imo)) if pd.notna(imo) else None
            records.append({
                "ship": str(row.get("Vessel name")),
                "imo": int(imo) if pd.notna(imo) else None,
                "eta": eta.to_pydatetime(),
                "section": section,
                "terminals": terminals,
                "dwt": info["dwt"] if info else None,
                "ship_type": info["ship_type"] if info else None,
            })
    return records
