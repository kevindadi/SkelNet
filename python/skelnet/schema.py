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
    elif not isinstance(cell["accepted"], bool):
        errors.append("accepted must be a bool")

    errors.extend(_validate_calls(cell.get("calls")))
    errors.extend(_validate_budget_used(cell.get("budget_used")))
    errors.extend(_validate_oracle(cell.get("oracle")))
    errors.extend(_validate_method_fields(cell))

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
    errors.extend(_validate_baseline_fields(cell))
    return errors


def _validate_method_fields(cell: Any) -> list[str]:
    """Type-check the SKEL/CIR method fields when present (G0/baselines omit)."""
    errors: list[str] = []
    for key in ("skel_verified", "rust_compiled"):
        if key in cell and not (cell[key] is None or isinstance(cell[key], bool)):
            errors.append(f"{key} must be a bool or null")
    for key in ("skel_status", "feedback_mode", "rust_when_unverified",
                "property_ids", "rust_skipped"):
        if key in cell and not (cell[key] is None or isinstance(cell[key], str)):
            errors.append(f"{key} must be a string or null")
    if "rust_calls" in cell and (not isinstance(cell["rust_calls"], int)
                                 or isinstance(cell["rust_calls"], bool)):
        errors.append("rust_calls must be an int")
    if "rust_attempts" in cell:
        attempts = cell["rust_attempts"]
        if not isinstance(attempts, list):
            errors.append("rust_attempts must be a list")
        else:
            for i, attempt in enumerate(attempts):
                if not isinstance(attempt, dict):
                    errors.append(f"rust_attempts[{i}] is not an object")
                    continue
                for key in ("call", "stage", "reply_kind", "compiled"):
                    if key not in attempt:
                        errors.append(f"rust_attempts[{i}].{key} is required")
                if "compile_wall_ms" in attempt and not _is_int_or_none(
                        attempt["compile_wall_ms"]):
                    errors.append(
                        f"rust_attempts[{i}].compile_wall_ms must be an int or null")
    if "compile_wall_ms" in cell and not _is_int_or_none(cell["compile_wall_ms"]):
        errors.append("compile_wall_ms must be an int or null")
    history = cell.get("history") if isinstance(cell, dict) else None
    if isinstance(history, list):
        for i, item in enumerate(history):
            if isinstance(item, dict) and "wall_ms" in item and not _is_int_or_none(
                    item["wall_ms"]):
                errors.append(f"history[{i}].wall_ms must be an int or null")
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
                    "finish_reason", "finish_reasons", "wall_ms"):
            if key not in call:
                errors.append(f"calls[{i}].{key} is required")
        if not isinstance(call.get("cache_hit"), bool):
            errors.append(f"calls[{i}].cache_hit must be a bool")
        if not isinstance(call.get("truncation_retry"), bool):
            errors.append(f"calls[{i}].truncation_retry must be a bool")
        if not isinstance(call.get("finish_reasons"), list):
            errors.append(f"calls[{i}].finish_reasons must be a list")
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
    if "o3_tools" in oracle and oracle["o3_tools"] is not None:
        errors.extend(_validate_o3_tools(oracle["o3_tools"]))
    return errors


def _validate_o3_tools(value: Any) -> list[str]:
    """Type-check the round-8 ``oracle.o3_tools`` sub-results when present."""
    if not isinstance(value, dict):
        return ["oracle.o3_tools must be an object or null"]
    errors: list[str] = []
    for name in ("shuttle", "miri"):
        sub = value.get(name)
        if not isinstance(sub, dict):
            errors.append(f"oracle.o3_tools.{name} must be an object")
            continue
        for key in ("status", "category"):
            if key not in sub:
                errors.append(f"oracle.o3_tools.{name}.{key} is required")
            elif not (sub[key] is None or isinstance(sub[key], str)):
                errors.append(
                    f"oracle.o3_tools.{name}.{key} must be a string or null")
    if not isinstance(value.get("no_concurrency"), bool):
        errors.append("oracle.o3_tools.no_concurrency must be a bool")
    return errors


def _validate_baseline_fields(cell: dict) -> list[str]:
    """Type-check ``baseline`` when a round-4 arm recorded one."""
    if "baseline" not in cell:
        return []
    baseline = cell["baseline"]
    if not isinstance(baseline, dict):
        return ["baseline must be an object"]
    errors: list[str] = []
    rounds = baseline.get("rounds")
    if not isinstance(rounds, list):
        errors.append("baseline.rounds must be a list")
    else:
        for i, round_ in enumerate(rounds):
            if not isinstance(round_, dict):
                errors.append(f"baseline.rounds[{i}] must be an object")
                continue
            for key in ("call", "stage", "reply_kind", "version", "compiled",
                        "feedback_sha256", "feedback_bytes", "truncated"):
                if key not in round_:
                    errors.append(f"baseline.rounds[{i}].{key} is required")
            compiled = round_.get("compiled")
            if "compiled" in round_ and not (
                    compiled is None or isinstance(compiled, bool)):
                errors.append(f"baseline.rounds[{i}].compiled must be a bool or null")
            compile_state = round_.get("compile")
            if "compile" in round_ and compile_state not in (
                    None, "ok", "error", "unavailable", "timeout"):
                errors.append(
                    f"baseline.rounds[{i}].compile must be ok, error, "
                    "unavailable, timeout, or null")
            if compiled is None and round_.get("reply_kind") == "program" \
                    and compile_state not in ("unavailable", "timeout"):
                errors.append(
                    f"baseline.rounds[{i}].compile must be unavailable or "
                    "timeout when compiled is null")
            if "truncated" in round_ and not isinstance(round_["truncated"], bool):
                errors.append(f"baseline.rounds[{i}].truncated must be a bool")
            if "feedback_bytes" in round_ and (
                    not isinstance(round_["feedback_bytes"], int)
                    or isinstance(round_["feedback_bytes"], bool)):
                errors.append(f"baseline.rounds[{i}].feedback_bytes must be an int")
            if "compile_wall_ms" in round_ and not _is_int_or_none(
                    round_["compile_wall_ms"]):
                errors.append(
                    f"baseline.rounds[{i}].compile_wall_ms must be an int or null")
            tools = round_.get("tools")
            if isinstance(tools, dict):
                for name, tool in tools.items():
                    if isinstance(tool, dict) and "wall_ms" in tool and not _is_int_or_none(
                            tool["wall_ms"]):
                        errors.append(
                            f"baseline.rounds[{i}].tools.{name}.wall_ms "
                            "must be an int or null")
    if "accepted_at_call" in baseline and not _is_int_or_none(
            baseline["accepted_at_call"]):
        errors.append("baseline.accepted_at_call must be an int or null")
    reason = baseline.get("accept_reason")
    if "accept_reason" in baseline and not (reason is None or isinstance(reason, str)):
        errors.append("baseline.accept_reason must be a string or null")
    if not isinstance(baseline.get("final_version"), int) or isinstance(
            baseline.get("final_version"), bool):
        errors.append("baseline.final_version must be an int")
    hit = baseline.get("first_round_cache_hit")
    if "first_round_cache_hit" in baseline and not (
            hit is None or isinstance(hit, bool)):
        errors.append("baseline.first_round_cache_hit must be a bool or null")
    missing = baseline.get("tools_missing")
    if not isinstance(missing, list) or not all(isinstance(x, str) for x in missing):
        errors.append("baseline.tools_missing must be a list of strings")
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
        else:
            for key in ("category", "detail"):
                if not (layer[key] is None or isinstance(layer[key], str)):
                    errors.append(f"oracle.layers.{name}.{key} must be a string or null")
            if not _is_int_or_none(layer["wall_ms"]):
                errors.append(f"oracle.layers.{name}.wall_ms must be an int or null")
    return errors
