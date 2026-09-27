"""Per-property evidence ledger.

The ledger records the verification evidence for the skeleton/CIR artifact
separately from the Rust code score, so the two are never conflated.
"""

from __future__ import annotations

from typing import Any


def property_ledger(verify_payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    payload = verify_payload or {}
    out: dict[str, dict[str, Any]] = {}
    for p in payload.get("properties", []) or []:
        out[p.get("id")] = {"outcome": p.get("outcome"), "reqs": p.get("reqs") or []}
    return out


def evidence_sufficient(verify_payload: dict[str, Any] | None) -> bool:
    """Sufficient when the artifact verified PASS and every property passed."""
    payload = verify_payload or {}
    if payload.get("outcome") != "PASS":
        return False
    props = payload.get("properties") or []
    return bool(props) and all(p.get("outcome") == "PASS" for p in props)


def requirement_coverage(ledger: dict[str, dict[str, Any]]) -> set[str]:
    covered: set[str] = set()
    for entry in ledger.values():
        covered.update(entry.get("reqs") or [])
    return covered
