"""Klient Groq (LLM) do generacji narracji raportow operacyjnych.

Uzywa istniejacego httpx i OpenAI-kompatybilnego endpointu Groq. Zwraca slownik
z polami headline/cause/recommendation/summary lub None przy bledzie (wtedy
warstwa raportow stosuje fallback regulowy).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

import httpx

from .config import settings

logger = logging.getLogger("port_traffic_pulse.groq")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = (
    "Jestes asystentem dyzurnego w centrum dowodzenia portu morskiego. "
    "Na podstawie ustrukturyzowanych danych o ruchu na drodze dojazdowej do terminala "
    "tworzysz krotki raport operacyjny po polsku. Pisz konkretnie, rzeczowo i zwiezle, "
    "jezykiem sluzb ruchu. Odbiorca to dyspozytor sterujacy ruchem ciezarowek.\n\n"
    "Zwroc WYLACZNIE obiekt JSON o polach:\n"
    '- "headline": krotki naglowek (max ~8 slow),\n'
    '- "cause": prawdopodobna przyczyna utrudnienia (1 zdanie),\n'
    '- "recommendation": konkretna rekomendacja dzialania dla dyspozytora (1-2 zdania),\n'
    '- "summary": pelne podsumowanie laczace stan, przyczyne, rekomendacje i trend '
    "(2-3 zdania).\n"
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
        "max_tokens": 500,
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
        return {
            "headline": str(parsed.get("headline", "")).strip(),
            "cause": str(parsed.get("cause", "")).strip(),
            "recommendation": str(parsed.get("recommendation", "")).strip(),
            "summary": str(parsed.get("summary", "")).strip(),
        }
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("Groq generacja nieudana dla %s: %s", situation.get("point_id"), exc)
        return None
    finally:
        if owns_client and client is not None:
            await client.aclose()
