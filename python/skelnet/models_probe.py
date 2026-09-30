"""`python -m skelnet models probe` — model parameter probe.

``--dry-run`` lists the four experimental models and their parameter policy and
reports only whether each API key is present (never its value). A real probe
(only run by the repository owner with keys) sends a few minimal requests and
writes ``PROBE.json``. The caller loads ``.env`` (via ``--env-file``) before
either mode.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from .models import normalize_token_usage
from .params import params_for_model
from .transport import CHANNELS, experimental_models

PROBE_SYSTEM = "You are a probe."
PROBE_USER = "Reply with the single word OK."
# A small concurrency question with one correct answer (YES). The trivial
# "OK" prompt can report zero reasoning tokens even when the model reasons.
PROBE_NONTRIVIAL_USER = (
    "Thread A locks X then Y; thread B locks Y then X; thread C locks X then Y. "
    "Each thread releases both locks before exiting. Can this program deadlock "
    "under some schedule? Think it through, then answer with exactly one word: "
    "YES or NO."
)


def _api_key_present(spec) -> bool:
    channel = CHANNELS.get(spec.channel)
    if channel is None:
        return False
    return bool(os.environ.get(channel.api_key_env))


def _policy(spec) -> dict[str, Any]:
    channel = CHANNELS.get(spec.channel)
    return {
        "display_name": spec.display_name,
        "model_id": spec.model_id,
        "channel": spec.channel,
        "provider": spec.provider,
        "surface": spec.surface,
        "base_url": channel.base_url if channel else None,
        "api_key_env": channel.api_key_env if channel else None,
        "status": spec.status,
        "thinking": spec.thinking,
        "reasoning_effort": spec.reasoning_effort,
        "max_output_tokens": spec.max_output_tokens,
        "max_output_tokens_cap": spec.max_output_tokens_cap,
        "supports_seed": spec.supports_seed,
        "stream": spec.stream,
        "api_key_present": _api_key_present(spec),
    }


def probe_dry_run(models=None) -> dict[str, Any]:
    specs = list(models) if models is not None else experimental_models()
    return {"dry_run": True, "models": [_policy(s) for s in specs]}


def probe_run(out_dir: Path | str, *, client_factory: Callable | None = None,
              models=None) -> dict[str, Any]:
    """Send minimal requests per model and write ``PROBE.json``.

    `client_factory(spec, params) -> client` lets tests inject fake clients;
    the real path builds one through ``channels.build_client``.
    """
    specs = list(models) if models is not None else experimental_models()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for spec in specs:
        if spec.status != "available" or not spec.model_id:
            records.append({**_policy(spec), "probed": False,
                            "reason": spec.blocked_reason or "unavailable"})
            continue

        def build(params, spec=spec):
            if client_factory is not None:
                return client_factory(spec, params)
            return _build_probe_client(spec, params, out_dir)

        records.append(_probe_one(spec, build))
    document = {"schema_version": "skelnet-probe-v1",
                "created_at": time.time(), "models": records}
    (out_dir / "PROBE.json").write_text(json.dumps(document, indent=2),
                                        encoding="utf-8")
    return document


def _build_probe_client(spec, params, out_dir):
    from .channels import build_client, key_for
    channel = CHANNELS[spec.channel]
    api_key = key_for(spec, dict(os.environ), channel.api_key_env)
    return build_client(spec, params, budget=_NullBudget(), evidence_dir=out_dir,
                        api_key=api_key)


class _NullBudget:
    def reserve(self) -> None:
        return None

    def add_tokens(self, _tokens) -> None:
        return None


def _reasoning_tokens(usage) -> int | None:
    return normalize_token_usage(usage).get("reasoning")


def _reasoning_content_present(outcome) -> bool:
    text = getattr(outcome, "reasoning_content", None)
    return bool(isinstance(text, str) and text.strip())


def _thinking_accepted(outcome) -> bool | None:
    reasoning = _reasoning_tokens(getattr(outcome, "usage", None))
    if (isinstance(reasoning, int) and reasoning > 0) or (
            _reasoning_content_present(outcome)):
        return True
    return None


def _output_includes_reasoning(usage) -> bool | None:
    tokens = normalize_token_usage(usage)
    if isinstance(tokens.get("output"), int) and isinstance(tokens.get("reasoning"), int):
        return tokens["output"] >= tokens["reasoning"]
    return None


def _fill_basic(record: dict, outcome) -> None:
    record["returned_model"] = getattr(outcome, "response_model", None)
    record["usage"] = getattr(outcome, "usage", None)
    record["finish_reason"] = getattr(outcome, "finish_reason", None)
    record["reasoning_content_present"] = _reasoning_content_present(outcome)
    record["seed_sent"] = getattr(outcome, "seed", None) is not None


def _answer_ok(text: str) -> bool:
    words = (text or "").strip().split()
    if not words:
        return False
    return words[-1].strip(".,;:").upper() == "YES"


def _output_tokens(usage) -> int | None:
    return normalize_token_usage(usage).get("output")


def _echo_has_effort(echo) -> bool:
    if not isinstance(echo, dict):
        return False
    effort = echo.get("effort")
    return isinstance(effort, str) and bool(effort.strip())


def _reasoning_diagnosis(spec, record: dict) -> str:
    """Why a probe did or did not observe reasoning on the nontrivial prompt."""
    if record.get("error"):
        return "probe_error"
    tokens = record.get("reasoning_tokens_nontrivial")
    if not isinstance(tokens, int):
        tokens = 0
    if tokens > 0:
        return "model_reasons"
    if spec.surface == "responses":
        echo = record.get("responses_reasoning_echo")
        if echo is None or not _echo_has_effort(echo):
            return "gateway_dropped_reasoning_param"
        return "reasoning_not_reported_or_not_used"
    if tokens == 0 and not record.get("nontrivial_reasoning_content"):
        return "no_reasoning_observed"
    return "no_reasoning_observed"


def _complete_probe(client, user: str):
    if hasattr(client, "set_cell"):
        client.set_cell("probe", 0)
    return client.complete(PROBE_SYSTEM, user)


def _append_nontrivial(record: dict, spec, build, params) -> None:
    """One default-effort nontrivial call, plus low and a summary probe."""
    try:
        client = build(params)
        outcome = _complete_probe(client, PROBE_NONTRIVIAL_USER)
    except Exception as exc:  # noqa: BLE001
        record["error"] = type(exc).__name__
        record["error_message"] = str(exc)
        record["reasoning_diagnosis"] = "probe_error"
        return
    record["reasoning_tokens_nontrivial"] = _reasoning_tokens(
        getattr(outcome, "usage", None))
    record["nontrivial_output_tokens"] = _output_tokens(getattr(outcome, "usage", None))
    record["nontrivial_answer_ok"] = _answer_ok(getattr(outcome, "text", "") or "")
    record["nontrivial_reasoning_content"] = _reasoning_content_present(outcome)
    if spec.surface == "responses":
        record["responses_reasoning_echo"] = getattr(
            outcome, "responses_reasoning_echo", None)
        record["responses_reasoning_items"] = getattr(
            outcome, "responses_reasoning_items", None)
        record["responses_output_tokens_details"] = getattr(
            outcome, "responses_output_tokens_details", None)
    if spec.reasoning_effort:
        try:
            low = build(params_for_model(spec, reasoning_effort="low"))
            low_out = _complete_probe(low, PROBE_NONTRIVIAL_USER)
            record["reasoning_tokens_nontrivial_low"] = _reasoning_tokens(
                getattr(low_out, "usage", None))
        except Exception:  # noqa: BLE001
            record["reasoning_tokens_nontrivial_low"] = None
    if spec.surface == "responses":
        try:
            summary_client = build(params)
            summary_client.reasoning_summary = "auto"
            summary_out = _complete_probe(summary_client, PROBE_NONTRIVIAL_USER)
            record["responses_reasoning_summary_present"] = bool(
                getattr(summary_out, "responses_reasoning_summary_present", False))
        except Exception:  # noqa: BLE001
            record["responses_reasoning_summary_present"] = None
    record["reasoning_diagnosis"] = _reasoning_diagnosis(spec, record)
    record.pop("nontrivial_reasoning_content", None)


def _probe_one(spec, build) -> dict[str, Any]:
    record = {**_policy(spec), "probed": True, "error": None,
              "thinking_accepted": None, "output_includes_reasoning": None,
              "requires_stream": None, "seed_deterministic": None,
              "reasoning_content_present": None,
              "reasoning_tokens_low": None, "reasoning_tokens_medium": None,
              "reasoning_tokens_high": None}
    params = params_for_model(spec)
    try:
        client = build(params)
        if hasattr(client, "set_cell"):
            client.set_cell("probe", 0)
        first = client.complete(PROBE_SYSTEM, PROBE_USER)
        _fill_basic(record, first)
        record["requires_stream"] = False
        record["thinking_accepted"] = _thinking_accepted(first)
        record["output_includes_reasoning"] = _output_includes_reasoning(
            getattr(first, "usage", None))
        if getattr(first, "seed", None) is not None:
            second = client.complete(PROBE_SYSTEM, PROBE_USER)
            record["seed_deterministic"] = (
                getattr(second, "text", None) == getattr(first, "text", None))
    except Exception as exc:  # noqa: BLE001
        record["thinking_accepted"] = False
        record["error"] = type(exc).__name__
        record["error_message"] = str(exc)
        if spec.channel == "dashscope-direct":
            _probe_stream_fallback(record, spec, build)
        if record.get("error"):
            record["reasoning_diagnosis"] = "probe_error"
            return record
        _append_nontrivial(record, spec, build, params)
        return record

    # Reasoning-effort variation for the reasoning models. Moonshot
    # ``kimi-k2.7-code`` has no ``reasoning_effort`` (R9c), so it takes no
    # variant; OpenCode GPT uses low/medium.
    if spec.surface == "responses" or spec.channel == "opencode-go":
        variants = (("low", "reasoning_tokens_low"),
                    ("medium", "reasoning_tokens_medium"))
    else:
        variants = ()
    if variants:
        for effort, key in variants:
            try:
                variant = build(params_for_model(spec, reasoning_effort=effort))
                if hasattr(variant, "set_cell"):
                    variant.set_cell("probe", 0)
                out = variant.complete(PROBE_SYSTEM, PROBE_USER)
                record[key] = _reasoning_tokens(getattr(out, "usage", None))
            except Exception:  # noqa: BLE001
                record[key] = None
    _append_nontrivial(record, spec, build, params)
    return record


def _probe_stream_fallback(record: dict, spec, build) -> None:
    try:
        client = build(params_for_model(spec, stream=True))
        if hasattr(client, "set_cell"):
            client.set_cell("probe", 0)
        outcome = client.complete(PROBE_SYSTEM, PROBE_USER)
        _fill_basic(record, outcome)
        record["requires_stream"] = True
        record["thinking_accepted"] = _thinking_accepted(outcome)
        record["output_includes_reasoning"] = _output_includes_reasoning(
            getattr(outcome, "usage", None))
        record["error"] = None
    except Exception as exc:  # noqa: BLE001
        record["requires_stream"] = None
        record["error"] = type(exc).__name__
