"""Defensive extraction of a JSON object from model output."""

from __future__ import annotations

import json
import re

_THINK_TAG_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.DOTALL | re.IGNORECASE)

def extract_json(text: str) -> str:
    """Strip reasoning/fences and return the first decodable JSON value.

    The returned text is intentionally not parsed here. Keeping parse errors in
    the workflow lets the next LLM round receive the exact candidate that
    failed.
    """

    cleaned = _THINK_TAG_RE.sub("", text).strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        cleaned = cleaned[first_newline + 1 :] if first_newline >= 0 else cleaned[3:]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3].rstrip()

    try:
        _, end = json.JSONDecoder().raw_decode(cleaned)
        return cleaned[:end].strip()
    except json.JSONDecodeError:
        start = cleaned.find("{")
        if start < 0:
            return cleaned
        try:
            _, end = json.JSONDecoder().raw_decode(cleaned[start:])
        except json.JSONDecodeError:
            return cleaned
        return cleaned[start : start + end].strip()
