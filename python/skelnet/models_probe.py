"""`python -m skelnet models probe` — model parameter probe.

``--dry-run`` lists the four experimental models and their parameter policy and
reports only whether each API key is present (never its value). A real probe
(only run by the repository owner with keys) sends a few minimal requests and
writes ``PROBE.json``.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from .params import params_for_model
from .transport import CHANNELS, experimental_models


def _api_key_present(spec) -> bool:
    channel = CHANNELS.get(spec.channel)
    if channel is None:
        return False
    return bool(os.environ.get(channel.api_key_env))


def _policy(spec) -> dict[str, Any]:
    return {
        "display_name": spec.display_name,
        "model_id": spec.model_id,
        "channel": spec.channel,
        "provider": spec.provider,
        "surface": spec.surface,
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
        params = params_for_model(spec)
        try:
            client = (client_factory(spec, params) if client_factory
                      else _build_probe_client(spec, params, out_dir))
        except Exception as exc:  # noqa: BLE001
            records.append({**_policy(spec), "probed": False, "reason": str(exc)})
            continue
        records.append(_probe_one(spec, params, client))
    document = {"schema_version": "skelnet-probe-v1",
                "created_at": time.time(), "models": records}
    (out_dir / "PROBE.json").write_text(json.dumps(document, indent=2),
                                        encoding="utf-8")
    return document


def _build_probe_client(spec, params, out_dir):
    from .channels import build_client, key_for
    from .env import load_dotenv
    # The real probe (repository owner only) reads keys from the local .env.
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)
    channel = CHANNELS[spec.channel]
    api_key = key_for(spec, dict(os.environ), channel.api_key_env)
    return build_client(spec, params, budget=_NullBudget(), evidence_dir=out_dir,
                        api_key=api_key)


class _NullBudget:
    def reserve(self) -> None:
        return None


def _probe_one(spec, params, client) -> dict[str, Any]:
    record = {**_policy(spec), "probed": True}
    try:
        if hasattr(client, "set_cell"):
            client.set_cell("probe", 0)
        first = client.complete("You are a probe.", "Reply with the single word OK.")
        record["returned_model"] = getattr(first, "response_model", None)
        record["usage"] = getattr(first, "usage", None)
        record["finish_reason"] = getattr(first, "finish_reason", None)
        record["seed_sent"] = getattr(first, "seed", None) is not None
        if getattr(first, "seed", None) is not None:
            second = client.complete("You are a probe.", "Reply with the single word OK.")
            record["seed_deterministic"] = (
                getattr(second, "text", None) == getattr(first, "text", None))
        else:
            record["seed_deterministic"] = None
        record["thinking_accepted"] = True
        record["error"] = None
    except Exception as exc:  # noqa: BLE001
        record["error"] = type(exc).__name__
        record["error_message"] = str(exc)
    return record
