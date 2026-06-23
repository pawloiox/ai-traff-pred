"""Klient Groq (LLM) do generacji narracji raportow operacyjnych.

Uzywa istniejacego httpx i OpenAI-kompatybilnego endpointu Groq. Zwraca slownik
z polami headline/cause/recommendation/summary lub None przy bledzie (wtedy
warstwa raportow stosuje fallback regulowy).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from .config import settings

logger = logging.getLogger("port_traffic_pulse.groq")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

_FIELDS_DESC = (
    '- "headline": krotki naglowek (max ~8 slow),\n'
    '- "cause": prawdopodobna przyczyna utrudnienia (1 zdanie). Jesli podano dominujacy '
    "skladnik CPI, oprzyj na nim przyczyne (presja_portu = nadchodzacy statek/fala "
    "ciezarowek z terminala; trend = narastajaca dynamika; baseline = typowy ruch o tej "
    "porze; incydenty = zdarzenie drogowe),\n"
    '- "recommendation": konkretna rekomendacja dzialania dla dyspozytora (1-2 zdania),\n'
    '- "summary": pelne podsumowanie laczace stan, przyczyne, rekomendacje i trend '
    "(2-3 zdania).\n"
)

SYSTEM_PROMPT = (
    "Jestes asystentem dyzurnego w centrum dowodzenia portu morskiego. "
    "Na podstawie ustrukturyzowanych danych o ruchu na drodze dojazdowej do terminala "
    "tworzysz krotki raport operacyjny po polsku. Pisz konkretnie, rzeczowo i zwiezle, "
    "jezykiem sluzb ruchu. Odbiorca to dyspozytor sterujacy ruchem ciezarowek.\n\n"
    "Zwroc WYLACZNIE obiekt JSON o polach:\n" + _FIELDS_DESC +
    "Nie dodawaj zadnego tekstu poza obiektem JSON."
)

SYSTEM_PROMPT_BATCH = (
    "Jestes asystentem dyzurnego w centrum dowodzenia portu morskiego. "
    "Na podstawie listy ustrukturyzowanych sytuacji ruchu na drogach dojazdowych do "
    "terminali tworzysz krotkie raporty operacyjne po polsku. Pisz konkretnie, rzeczowo "
    "i zwiezle, jezykiem sluzb ruchu. Odbiorca to dyspozytor sterujacy ruchem ciezarowek.\n\n"
    "Otrzymasz liste sytuacji, kazda oznaczona polem id. Zwroc WYLACZNIE obiekt JSON "
    'w formacie: {"reports": [{"id": <to samo id>, "headline": ..., "cause": ..., '
    '"recommendation": ..., "summary": ...}, ...]}.\n'
    "Dla KAZDEJ sytuacji wygeneruj dokladnie jeden raport o tym samym id. Pola raportu:\n"
    + _FIELDS_DESC +
    "Nie dodawaj zadnego tekstu poza obiektem JSON."
)


def _situation_to_prompt(s: Dict[str, Any]) -> str:
    """Buduje czytelny opis sytuacji dla modelu."""
    lines = [
        f"Port: {s.get('port_id')}",
        f"Punkt pomiarowy: {s.get('point_name')}",
        f"Droga: {s.get('road')}",
        f"Poziom: {s.get('level')}",
        f"Srednia kongestia w ostatniej godzinie: {round((s.get('avg_ratio') or 0) * 100)}%",
        f"Maksymalna kongestia: {round((s.get('max_ratio') or 0) * 100)}%",
        f"Kongestia narasta: {'tak' if s.get('rising') else 'nie'}",
        f"Anomalia wzgledem typowego ruchu: {'tak' if s.get('is_anomaly') else 'nie'}",
        f"Droga zamknieta: {'tak' if s.get('road_closure') else 'nie'}",
    ]

    pred = s.get("prediction")
    if pred:
        lines.append(
            f"Prognoza na {pred.get('horizon_minutes')} min: "
            f"{round((pred.get('predicted_ratio') or 0) * 100)}% kongestii "
            f"(zmiana {round((pred.get('slope_per_10min') or 0) * 100, 1)} pkt%/10 min)"
        )

    inc = s.get("linked_incident")
    if inc:
        delay = inc.get("delay_seconds")
        delay_txt = f", opoznienie ok. {round(delay / 60)} min" if delay else ""
        lines.append(
            f"Pobliski incydent TomTom: {inc.get('category_label')} "
            f"- {inc.get('description')} (ok. {inc.get('distance_m')} m{delay_txt})"
        )
    else:
        lines.append("Pobliski incydent TomTom: brak")

    # Rozklad CPI (Indeks Presji Zatorowej) - dominujacy skladnik = przyczyna.
    cpi_s = s.get("cpi")
    if cpi_s:
        lines.append(
            f"CPI (prognoza na {round(cpi_s.get('horizon_h', 0))}h): {cpi_s.get('total')} "
            f"[baseline={cpi_s.get('baseline')}, trend={cpi_s.get('trend')}, "
            f"presja_portu={cpi_s.get('port_pressure')}, incydenty={cpi_s.get('incidents')}]"
        )
        lines.append(f"Dominujacy skladnik CPI (glowna przyczyna): {cpi_s.get('dominant_component')}")
        det = cpi_s.get("port_pressure_detail") or {}
        ship = det.get("dominant_ship")
        if ship:
            lines.append(
                f"Najwiekszy nadchodzacy statek: {ship.get('name')} (DWT {round(ship.get('dwt', 0))}) "
                f"- fala ciezarowek z terminala po cumowaniu"
            )

    return "\n".join(lines)


async def generate_report(
    situation: Dict[str, Any], client: Optional[httpx.AsyncClient] = None
) -> Optional[Dict[str, str]]:
    """Generuje narracje raportu przez Groq. Zwraca dict lub None przy bledzie."""
    if not settings.groq_enabled or not settings.groq_api_key:
        return None

    payload = {
        "model": settings.groq_model,
        "temperature": 0.3,
        "max_tokens": 300,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _situation_to_prompt(situation)},
        ],
    }
    headers = {
        "Authorization": f"Bearer {settings.groq_api_key}",
        "Content-Type": "application/json",
    }

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=settings.groq_timeout)
    try:
        resp = await client.post(GROQ_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return _normalize_narrative(parsed)
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("Groq generacja nieudana dla %s: %s", situation.get("point_id"), exc)
        return None
    finally:
        if owns_client and client is not None:
            await client.aclose()


def _normalize_narrative(parsed: Dict[str, Any]) -> Dict[str, str]:
    return {
        "headline": str(parsed.get("headline", "")).strip(),
        "cause": str(parsed.get("cause", "")).strip(),
        "recommendation": str(parsed.get("recommendation", "")).strip(),
        "summary": str(parsed.get("summary", "")).strip(),
    }


async def generate_reports_batch(
    situations: List[Dict[str, Any]], client: Optional[httpx.AsyncClient] = None
) -> List[Optional[Dict[str, str]]]:
    """Generuje narracje dla wielu sytuacji w JEDNYM zapytaniu Groq.

    Zwraca liste narracji wyrownana do `situations` (None tam, gdzie model nie
    zwrocil raportu). Oszczedza limit (1 request/cykl zamiast N).
    """
    result: List[Optional[Dict[str, str]]] = [None] * len(situations)
    if not situations or not settings.groq_enabled or not settings.groq_api_key:
        return result

    blocks = []
    for idx, s in enumerate(situations):
        blocks.append(f"### Sytuacja id={idx}\n{_situation_to_prompt(s)}")
    user_content = "\n\n".join(blocks)

    # Budzet wyjscia skalowany liczba sytuacji (ok. 180 tokenow na raport).
    max_tokens = min(2000, 180 * len(situations) + 120)

    payload = {
        "model": settings.groq_model,
        "temperature": 0.3,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_BATCH},
            {"role": "user", "content": user_content},
        ],
    }
    headers = {
        "Authorization": f"Bearer {settings.groq_api_key}",
        "Content-Type": "application/json",
    }

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=settings.groq_timeout)
    try:
        resp = await client.post(GROQ_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        reports = parsed.get("reports") if isinstance(parsed, dict) else None
        if not isinstance(reports, list):
            return result
        for item in reports:
            if not isinstance(item, dict):
                continue
            try:
                idx = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            if 0 <= idx < len(result):
                result[idx] = _normalize_narrative(item)
        return result
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("Groq generacja zbiorcza nieudana: %s", exc)
        return result
    finally:
        if owns_client and client is not None:
            await client.aclose()
