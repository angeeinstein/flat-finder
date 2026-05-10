"""Ollama-backed LLM extraction for apartment listing descriptions.

Completely non-blocking: every public function returns an empty dict on
any error (connection refused, timeout, bad JSON, wrong model, etc.).
Callers must never rely on this for correctness — it only fills in fields
that the HTML parser could not find.

Usage:
    from app.services.llm import extract_fields
    fields = extract_fields(description_text)  # always returns a dict
"""
from __future__ import annotations

import json
import logging

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 25           # seconds — generous for CPU-only inference
_DEFAULT_URL = "http://localhost:11434"
_DEFAULT_MODEL = "llama3.2:3b"   # phi3:mini is a good alternative

_PROMPT = """\
You are a structured real-estate data extractor. Read the apartment listing text and return a single JSON object. Use null for any field you are not confident about.

Fields:
- "pets_allowed": true / false / null
- "internet_included": true / false / null
- "is_private_landlord": true / false / null  (true = private person, false = agency/broker)
- "available_from": "YYYY-MM-DD" / null  (when the flat is available; "ab sofort" → today's date)
- "floor": string / null  (e.g. "3", "EG", "DG", "4. OG")
- "key_money": number / null  (Ablöse in EUR — one-time payment to previous tenant)
- "lease_is_limited": true / false / null  (befristet=true, unbefristet=false)

Listing text:
---
{text}
---

Return ONLY the JSON object. No explanation, no markdown."""


def _call_ollama(text: str, model: str, url: str) -> dict:
    payload = {
        "model": model,
        "prompt": _PROMPT.format(text=text[:4000]),
        "stream": False,
        "format": "json",
    }
    resp = requests.post(f"{url}/api/generate", json=payload, timeout=_TIMEOUT)
    resp.raise_for_status()
    raw = resp.json().get("response", "")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected dict, got {type(parsed).__name__}")
    return parsed


def extract_fields(
    text: str,
    model: str = _DEFAULT_MODEL,
    ollama_url: str = _DEFAULT_URL,
) -> dict:
    """Extract structured fields from a listing description via Ollama.

    Returns a (possibly empty) dict — never raises.
    """
    if not text or not text.strip():
        return {}
    try:
        result = _call_ollama(text.strip(), model=model, url=ollama_url)
        logger.debug("LLM extracted %d field(s)", len([v for v in result.values() if v is not None]))
        return result
    except requests.exceptions.ConnectionError:
        logger.debug("Ollama not reachable at %s — skipping LLM extraction", ollama_url)
        return {}
    except requests.exceptions.Timeout:
        logger.debug("Ollama timed out after %ds — skipping LLM extraction", _TIMEOUT)
        return {}
    except Exception as exc:
        logger.debug("LLM extraction skipped (%s: %s)", type(exc).__name__, exc)
        return {}
