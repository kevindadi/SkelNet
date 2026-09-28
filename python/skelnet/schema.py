"""Validate the frozen per-cell result schema (``skelnet-cell-v1``)."""

from __future__ import annotations

from typing import Any

SCHEMA_VERSION = "skelnet-cell-v1"

_STATUSES = {"ok", "error", "skipped"}
_TERMINAL_CHECKS = {"pass", "fail", "absent", "not_applicable", "not_run"}
_LAYER_STATUSES = {"pass", "fail", "unsupported", "unavailable", "not_run"}
_LAYER_KEYS = {"O1", "O2", "O3", "O4"}
_USAGE_KEYS = ("input", "output", "reasoning", "cached")


def _is_int_or_none(value: Any) -> bool:
    return value is None or (isinstance(value, int) and not isinstance(value, bool))


def validate_cell(cell: Any) -> list[str]:
    """Return a list of schema violations (empty means valid)."""
    errors: list[str] = []
    if not isinstance(cell, dict):
        return ["cell is not an object"]

    if cell.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r}")

    for key in ("arm", "model", "model_id", "task", "hint"):
        if not isinstance(cell.get(key), str) or not cell.get(key):
            errors.append(f"{key} must be a non-empty string")
    if "tier" not in cell:
        errors.append("tier is required (may be null)")
    elif cell["tier"] is not None and not isinstance(cell["tier"], str):
        errors.append("tier must be a string or null")
    if not isinstance(cell.get("rep"), int) or isinstance(cell.get("rep"), bool):
        errors.append("rep must be an int")
    if not _is_int_or_none(cell.get("seed")):
        errors.append("seed must be an int or null")

    status = cell.get("status")
    if status not in _STATUSES:
        errors.append(f"status must be one of {sorted(_STATUSES)}")
    if "skip_reason" not in cell:
        errors.append("skip_reason is required (may be null)")
    if "error" not in cell:
        errors.append("error is required (may be null)")
    if "accepted" not in cell:
        errors.append("accepted is required")

    errors.extend(_validate_calls(cell.get("calls")))
    errors.extend(_validate_budget_used(cell.get("budget_used")))
    errors.extend(_validate_oracle(cell.get("oracle")))

    for key in ("parse_ok", "check_ok", "evidence_sufficient"):
        if not isinstance(cell.get(key), bool):
            errors.append(f"{key} must be a bool")
    if not isinstance(cell.get("history"), list):
        errors.append("history must be a list")
    if not isinstance(cell.get("ledger"), dict):
        errors.append("ledger must be an object")
    if not isinstance(cell.get("rounds_used"), int) or isinstance(
            cell.get("rounds_used"), bool):
        errors.append("rounds_used must be an int")
    if not isinstance(cell.get("rust_mode"), str):
        errors.append("rust_mode must be a string")
    return errors


def _validate_calls(calls: Any) -> list[str]:
    if not isinstance(calls, list):
        return ["calls must be a list"]
    errors = []
    for i, call in enumerate(calls):
        if not isinstance(call, dict):
            errors.append(f"calls[{i}] is not an object")
            continue
        for key in ("attempt", "stage", "system_sha256", "request_sha256",
                    "cache_hit", "transport_attempt", "truncation_retry",
                    "finish_reason", "wall_ms"):
            if key not in call:
                errors.append(f"calls[{i}].{key} is required")
        if not isinstance(call.get("cache_hit"), bool):
            errors.append(f"calls[{i}].cache_hit must be a bool")
        if not isinstance(call.get("truncation_retry"), bool):
            errors.append(f"calls[{i}].truncation_retry must be a bool")
        errors.extend(_validate_usage(call.get("usage"), f"calls[{i}].usage"))
    return errors


def _validate_usage(usage: Any, where: str) -> list[str]:
    if not isinstance(usage, dict):
        return [f"{where} must be an object"]
    errors = []
    for key in _USAGE_KEYS:
        if key not in usage:
            errors.append(f"{where}.{key} is required")
        elif not _is_int_or_none(usage[key]):
            errors.append(f"{where}.{key} must be an int or null")
    return errors


def _validate_budget_used(budget: Any) -> list[str]:
    if not isinstance(budget, dict):
        return ["budget_used must be an object"]
    errors = []
    for key in ("calls", "tokens"):
        if not isinstance(budget.get(key), int) or isinstance(budget.get(key), bool):
            errors.append(f"budget_used.{key} must be an int")
    return errors


def _validate_oracle(oracle: Any) -> list[str]:
    if not isinstance(oracle, dict):
        return ["oracle must be an object"]
    errors = []
    for key in ("built", "ran", "run_ok"):
        if not isinstance(oracle.get(key), bool):
            errors.append(f"oracle.{key} must be a bool")
    for key in ("functional_ok", "functional_ok_no_o4"):
        if key in oracle and not (oracle[key] is None or isinstance(oracle[key], bool)):
            errors.append(f"oracle.{key} must be a bool or null")
    if oracle.get("terminal_check") not in _TERMINAL_CHECKS:
        errors.append(f"oracle.terminal_check must be one of {sorted(_TERMINAL_CHECKS)}")
    if "oracle_complete" in oracle and not isinstance(oracle["oracle_complete"], bool):
        errors.append("oracle.oracle_complete must be a bool")
    layers = oracle.get("layers")
    if layers is not None:
        errors.extend(_validate_layers(layers))
    return errors


def _validate_layers(layers: Any) -> list[str]:
    if not isinstance(layers, dict):
        return ["oracle.layers must be an object"]
    errors = []
    for name, layer in layers.items():
        if name not in _LAYER_KEYS:
            errors.append(f"oracle.layers has unknown key {name!r}")
            continue
        if not isinstance(layer, dict):
            errors.append(f"oracle.layers.{name} is not an object")
            continue
        if layer.get("status") not in _LAYER_STATUSES:
            errors.append(
                f"oracle.layers.{name}.status must be one of {sorted(_LAYER_STATUSES)}")
        if "category" not in layer or "detail" not in layer or "wall_ms" not in layer:
            errors.append(f"oracle.layers.{name} needs category/detail/wall_ms")
    return errors
