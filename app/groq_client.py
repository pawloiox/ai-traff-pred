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
    '- "headline": zwiezly naglowek raportu (max 5 slow)\n'
    '- "cause": formalna przyczyna utrudnienia (1 pelne zdanie w stylu oficjalnym)\n'
    '- "recommendation": rekomendacja operacyjna dla dyspozytora terminala (1 pelne zdanie)\n'
    '- "driver_action": WNIOSEK KONCOWY — jednoznaczna dyrektywa dla kierowcow ciezarowek: '
    'co powinni zrobic (np. wstrzymac wyjazd, skorzystac z trasy alternatywnej, '
    'zachowac ostroznosc, kontynuowac planowany przejazd). Musi byc konkretny i jednoznaczny (1-2 zdania)\n'
    '- "summary": profesjonalne podsumowanie sytuacji (max 2 zdania, styl formalny/urzedowy)\n'
)

_FORMAL_STYLE_INSTRUCTION = (
    "STYL RAPORTU: Uzywaj WYLACZNIE formalnego, profesjonalnego jezyka urzedowego. "
    "Unikaj potocznych sformułowan, skrotow myslowych i nieformalnego tonu. "
    "Raport bedzie czytany przez kadre zarzadzajaca i operatorow logistycznych. "
    "Kazde pole musi brzmiec jak oficjalny komunikat operacyjny.\n"
)

SYSTEM_PROMPT = (
    "Analityk operacyjny centrum zarzadzania ruchem portowym. "
    "Generujesz formalne raporty operacyjne w jezyku polskim dla dyspozytorow terminala.\n"
    + _FORMAL_STYLE_INSTRUCTION +
    "Jesli pogoda=deszcz lub czas=godziny szczytu, uwzglednij te czynniki w polu 'cause'.\n"
    "Pole 'driver_action' jest OBOWIAZKOWE — musi zawierac konkretny wniosek koncowy "
    "dotyczacy dzialania kierowcow ciezarowek w kontekscie biezacej sytuacji drogowej.\n\n"
    "Zwroc WYLACZNIE obiekt JSON o polach:\n" + _FIELDS_DESC +
    "Nie dodawaj zadnego tekstu poza obiektem JSON."
)

SYSTEM_PROMPT_BATCH = (
    "Analityk operacyjny centrum zarzadzania ruchem portowym. "
    "Generujesz formalne raporty operacyjne w jezyku polskim dla dyspozytorow terminala.\n"
    + _FORMAL_STYLE_INSTRUCTION +
    "Jesli pogoda=deszcz lub czas=godziny szczytu, uwzglednij te czynniki w polu 'cause'.\n"
    "Pole 'driver_action' jest OBOWIAZKOWE — musi zawierac konkretny wniosek koncowy "
    "dotyczacy dzialania kierowcow ciezarowek.\n\n"
    "Otrzymasz liste sytuacji, kazda oznaczona polem id. Zwroc WYLACZNIE obiekt JSON "
    'w formacie: {"reports": [{"id": 0, "headline": "txt", "cause": "txt", '
    '"recommendation": "txt", "driver_action": "txt", "summary": "txt"}]}.\n'
    "Dla KAZDEJ sytuacji wygeneruj dokladnie jeden raport o tym samym id. Pola raportu:\n"
    + _FIELDS_DESC +
    "Nie dodawaj zadnego tekstu poza obiektem JSON."
)

SYSTEM_PROMPT_GLOBAL_ONDEMAND = (
    "Glowny analityk centrum zarzadzania ruchem portowym. "
    "Sporzadz formalny, profesjonalny raport zbiorczy dotyczacy biezacej sytuacji drogowej. "
    "Nawet przy braku zatorow raport powinien informowac o stabilnej sytuacji.\n"
    + _FORMAL_STYLE_INSTRUCTION +
    "Pole 'driver_action' jest OBOWIAZKOWE — musi zawierac zbiorczy wniosek koncowy "
    "co do zalecanych dzialan dla kierowcow ciezarowek obslugujacych terminale portowe.\n\n"
    "Zwroc WYLACZNIE obiekt JSON o polach:\n"
    '- "headline": max 5 slow\n'
    '- "driver_action": wniosek koncowy dla kierowcow ciezarowek (1-2 zdania)\n'
    '- "summary": max 3 zdania, styl formalny/urzedowy\n'
)

def _situation_to_prompt(s: Dict[str, Any]) -> str:
    lines = [
        f"P:{s.get('point_name')}",
        f"Lvl:{s.get('level')} Kong:{round((s.get('avg_ratio') or 0)*100)}%",
        f"Rosnie:{s.get('rising')} Anomalia:{s.get('is_anomaly')}",
    ]
    pred = s.get("prediction")
    if pred:
        lines.append(f"Prog:{pred.get('horizon_minutes')}m->{round((pred.get('predicted_ratio') or 0)*100)}%")
    inc = s.get("linked_incident")
    if inc:
        lines.append(f"Incydent:{inc.get('description')}")
    w = s.get('weather') or {}
    if w.get('is_raining'): lines.append("Deszcz")
    t = s.get('temporal') or {}
    if t.get('is_rush_hour'): lines.append("Szczyt")

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
        client = httpx.AsyncClient(trust_env=False, timeout=settings.groq_timeout)
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
        "driver_action": str(parsed.get("driver_action", "")).strip(),
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
        client = httpx.AsyncClient(trust_env=False, timeout=settings.groq_timeout)
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


async def generate_global_report(
    situations: List[Dict[str, Any]], client: Optional[httpx.AsyncClient] = None
) -> Optional[Dict[str, str]]:
    """Generuje jeden globalny raport dla wszystkich sytuacji na zadanie."""
    if not settings.groq_enabled or not settings.groq_api_key:
        return None

    blocks = []
    for s in situations:
        blocks.append(f"Punkt: {s.get('point_name')} ({s.get('port_id')})\n"
                      f"  Poziom: {s.get('level')}\n"
                      f"  Kongestia: {round((s.get('avg_ratio') or 0) * 100)}%\n"
                      f"  Pogoda: Deszcz={s.get('weather', {}).get('is_raining', False)}")
    
    if not blocks:
        user_content = "Brak aktywnych punktow pomiarowych do analizy."
    else:
        user_content = "Aktualny stan wezlow:\n" + "\n".join(blocks)

    payload = {
        "model": settings.groq_model,
        "temperature": 0.4,
        "max_tokens": 400,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_GLOBAL_ONDEMAND},
            {"role": "user", "content": user_content},
        ],
    }
    headers = {
        "Authorization": f"Bearer {settings.groq_api_key}",
        "Content-Type": "application/json",
    }

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(trust_env=False, timeout=settings.groq_timeout)
    try:
        resp = await client.post(GROQ_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return {
            "headline": str(parsed.get("headline", "Raport Globalny")).strip(),
            "driver_action": str(parsed.get("driver_action", "")).strip(),
            "summary": str(parsed.get("summary", "")).strip(),
            "timestamp": "Teraz"
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Groq globalna generacja nieudana: %s", exc)
        return None
    finally:
        if owns_client and client is not None:
            await client.aclose()
