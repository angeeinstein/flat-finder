"""Ollama-backed LLM extraction for apartment listing descriptions.

Completely non-blocking: every public function returns an empty dict on
any error (connection refused, timeout, bad JSON, wrong model, etc.).
Callers must never rely on this for correctness — it only fills in fields
that the HTML parser could not find.

Usage:
    from app.services.llm import extract_fields
    fields = extract_fields(description_text, context="Preis: 800 EUR\\nFläche: 60 m²")
"""
from __future__ import annotations

import json
import logging
import re

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 90           # seconds — runs async in its own RQ job, so a long wait is fine
_DEFAULT_URL = "http://localhost:11434"
_DEFAULT_MODEL = "llama3.2:3b"

_PROMPT = """\
You are a structured real-estate data extractor. Read the apartment listing and return a single JSON object. Use null for any field you are not confident about.

Structured listing data (already extracted by the parser):
---
{context}
---

Listing description text:
---
{text}
---

Fields:
- "pets_allowed": true / false / null
- "internet_included": true / false / null
- "is_private_landlord": true / false / null  (true = private person, false = agency/broker)
- "available_from": "YYYY-MM-DD" / null  ("ab sofort" → today's date)
- "floor": string / null  (e.g. "3", "EG", "DG", "4. OG")
- "key_money": number / null  (Ablöse in EUR — one-time payment to previous tenant)
- "lease_is_limited": true / false / null  (befristet=true, unbefristet=false)
- "has_elevator": true / false / null  (Aufzug vorhanden)
- "is_renovated": true / false / null  (frisch saniert / renoviert = true, unsaniert = false)
- "wg_suitable": true / false / null  (WG-geeignet, Wohngemeinschaft ausdrücklich erlaubt)
- "year_built": number / null  (Baujahr als vierstellige Zahl)
- "laundry_available": true / false / null  (Waschmaschine in der Wohnung oder Waschküche im Haus)
- "summary": string / null  — Schreibe 2–3 sachliche Sätze auf Deutsch, die das Inserat zusammenfassen. Nutze die strukturierten Daten UND den Beschreibungstext. Nenne Preis, Größe, Lage und wichtige Ausstattungsmerkmale. Kein Werbejargon.

Return ONLY the JSON object. No explanation, no markdown."""


def _call_ollama(text: str, context: str, model: str, url: str) -> dict:
    prompt = _PROMPT.format(text=text[:3500], context=context[:600])
    payload = {"model": model, "prompt": prompt, "stream": False, "format": "json"}
    resp = requests.post(f"{url}/api/generate", json=payload, timeout=_TIMEOUT)
    if resp.status_code == 500:
        # Some Ollama versions / model states reject format:"json"; retry without it.
        logger.debug("Ollama 500 with format:json — retrying without format constraint")
        payload.pop("format")
        resp = requests.post(f"{url}/api/generate", json=payload, timeout=_TIMEOUT)
    resp.raise_for_status()
    raw = resp.json().get("response", "").strip()
    # Strip markdown code fences the model may add when format:"json" is absent
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw.strip())
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected dict, got {type(parsed).__name__}")
    return parsed


def extract_fields(
    text: str,
    context: str = "",
    model: str = _DEFAULT_MODEL,
    ollama_url: str = _DEFAULT_URL,
) -> dict:
    """Extract structured fields and generate a German summary via Ollama.

    Returns a (possibly empty) dict — never raises.
    """
    if not text or not text.strip():
        return {}
    try:
        result = _call_ollama(text.strip(), context=context, model=model, url=ollama_url)
        logger.info("LLM extracted %d field(s)", len([v for v in result.values() if v is not None]))
        return result
    except requests.exceptions.ConnectionError:
        logger.warning("Ollama not reachable at %s — skipping LLM extraction", ollama_url)
        return {}
    except requests.exceptions.Timeout:
        logger.warning("Ollama timed out after %ds — skipping LLM extraction", _TIMEOUT)
        return {}
    except Exception as exc:
        logger.warning("LLM extraction skipped (%s: %s)", type(exc).__name__, exc)
        return {}
