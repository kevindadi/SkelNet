"""Deterministic synthetic run-directory generator (round-8 fixtures).

``make_runs(root, spec)`` writes ``root/<model_slug>/<label>/`` run
directories whose ``MANIFEST.json`` and ``cells/<task>/<rep>/result.json``
follow the frozen ``skelnet-cell-v1`` schema (see ``docs/result-schema.md``)
and the real field names written by ``pipeline.py`` and ``baselines.py``.

The generator uses only :mod:`random.Random` instances seeded from
``hashlib`` digests, so two calls with the same spec produce byte-identical
trees.  No global RNG is touched.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

HINT = "h1"
CALL_BUDGET = 5

# ── the four experimental models (mirrors transport.build_registry) ──────

MODELS = [
    {
        "slug": "gpt", "display_name": "GPT 6 Luna", "model_id": "gpt-6-luna",
        "provider": "openai", "channel": "opencode-go", "surface": "responses",
        "thinking": True, "reasoning_effort": "medium",
        "supports_seed": False,
    },
    {
        "slug": "kimi", "display_name": "Kimi", "model_id": "kimi-k3",
        "provider": "moonshot", "channel": "moonshot-direct", "surface": "chat",
        "thinking": "always", "reasoning_effort": "high",
        "supports_seed": False,
    },
    {
        "slug": "deepseek", "display_name": "DeepSeek Flash",
        "model_id": "deepseek-flash", "provider": "deepseek",
        "channel": "deepseek-direct", "surface": "chat",
        "thinking": True, "reasoning_effort": None, "supports_seed": True,
    },
    {
        "slug": "qwen", "display_name": "Qwen", "model_id": "qwen3.8-flash",
        "provider": "qwen", "channel": "dashscope-direct", "surface": "chat",
        "thinking": True, "reasoning_effort": None, "supports_seed": False,
    },
]

# ── the seven main groups plus the SKEL-outcome ablation ────────────────

DEFAULT_GROUPS = [
    {"label": "G0", "arm": "G0", "kind": "g0"},
    {"label": "REFINE", "arm": "REFINE", "kind": "baseline"},
    {"label": "STATIC", "arm": "STATIC", "kind": "baseline"},
    {"label": "DYNAMIC", "arm": "DYNAMIC", "kind": "baseline"},
    {"label": "DYNAMIC_M", "arm": "DYNAMIC_M", "kind": "baseline"},
    {"label": "SKEL", "arm": "SKEL", "kind": "skel"},
    {"label": "CIR", "arm": "CIR", "kind": "cir"},
    {"label": "SKEL-outcome", "arm": "SKEL", "kind": "skel",
     "feedback_mode": "outcome_only"},
]

FAIL_COLUMNS = ("build", "policy", "hang", "output", "deadl", "other",
                "design", "monitor")
FEATURES = ("instrument_unsupported", "shuttle_unsupported", "miri_unsupported",
            "no_concurrency")


def _seed(*parts) -> int:
    blob = "|".join(str(p) for p in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(blob).digest()[:8], "big")


def _slug(label: str) -> str:
    return label.lower().replace("-", "_").replace(" ", "_")


def _usage(rng: random.Random, scale: int = 1) -> dict:
    base_in = rng.randint(700, 2200) * scale
    out = rng.randint(150, 900) * scale
    reasoning = rng.choice([0, 0, out // 2])
    cached = rng.choice([None, None, base_in // 4])
    return {"input": base_in, "output": out, "reasoning": reasoning,
            "cached": cached}


def _call(index: int, stage: str, rng: random.Random, *,
          cache_hit: bool = False, truncation_retry: bool = False,
          transport_attempt: int = 1) -> dict:
    usage = _usage(rng)
    return {
        "attempt": index,
        "stage": stage,
        "system_sha256": hashlib.sha256(f"sys{stage}".encode()).hexdigest(),
        "request_sha256": hashlib.sha256(f"req{index}{stage}".encode()).hexdigest(),
        "cache_hit": cache_hit,
        "transport_attempt": transport_attempt,
        "truncation_retry": truncation_retry,
        "finish_reason": "length" if truncation_retry else "stop",
        "finish_reasons": (["length", "stop"] if truncation_retry else ["stop"]),
        "usage": usage,
        "wall_ms": rng.randint(500, 4000),
        "error": None,
    }


def _layer(status: str, category=None, detail=None, wall_ms=None) -> dict:
    return {"status": status, "category": category, "detail": detail,
            "wall_ms": wall_ms}


def _oracle(plan: dict, rng: random.Random) -> dict:
    """Build the shared four-layer oracle sub-dict from a cell plan."""
    ok = plan["ok"]
    fail = plan.get("fail")
    features = set(plan.get("features") or ())
    old_o3 = plan.get("old_o3", False)

    o1_fail = fail in ("build", "policy")
    o2_fail = fail in ("hang", "output")
    o3_fail = fail in ("deadl", "other")
    o4_fail = fail in ("design", "monitor")

    o1 = _layer("fail" if fail == "build" else
                ("fail" if fail == "policy" else "pass"),
                {"build": "no_build", "policy": "policy_violation"}.get(fail),
                wall_ms=rng.randint(5, 40))
    o2 = _layer("fail" if o2_fail else "pass",
                {"hang": "hang", "output": "wrong_output"}.get(fail),
                wall_ms=rng.randint(5, 30))

    shuttle_status = "unsupported" if "shuttle_unsupported" in features else "pass"
    miri_status = "unsupported" if "miri_unsupported" in features else "pass"
    no_conc = "no_concurrency" in features
    if fail == "deadl":
        o3_status, o3_cat = "fail", "deadlock"
        shuttle_status, miri_status = "fail", "pass"
    elif fail == "other":
        o3_status, o3_cat = "fail", "panic"
    elif shuttle_status == "unsupported" and miri_status == "unsupported":
        o3_status, o3_cat = "unsupported", "shuttle_unsupported"
    elif shuttle_status == "unsupported" and miri_status == "fail":
        o3_status, o3_cat = "fail", "ub"
    else:
        o3_status = "pass"
        o3_cat = None
        if shuttle_status == "unsupported":
            o3_cat = "shuttle_unsupported"
        elif miri_status == "unsupported":
            o3_cat = "miri_unsupported"

    detail = None
    if no_conc:
        detail = "no concurrency to explore"
    if old_o3 and shuttle_status == "unsupported" and not detail:
        detail = "shuttle unsupported; miri pass"
    if ok is None and fail is None:
        o3_status, o3_cat = "unavailable", "tools_unavailable"
        detail = "shuttle and miri both unavailable"
    o3 = _layer(o3_status, o3_cat, detail, wall_ms=rng.randint(50, 400))

    if "instrument_unsupported" in features:
        o4_status, o4_cat = "unsupported", "instrument_unsupported"
    elif fail == "design":
        o4_status, o4_cat = "fail", "design_loss"
    elif fail == "monitor":
        o4_status, o4_cat = "fail", "monitor_fail"
    else:
        o4_status, o4_cat = "pass", None
    o4 = _layer(o4_status, o4_cat, wall_ms=rng.randint(20, 300))

    layers = {"O1": o1, "O2": o2, "O3": o3, "O4": o4}

    no_o4 = ok
    if ok is False and fail in ("design", "monitor"):
        no_o4 = True
    if ok is None:
        no_o4 = None

    skipped = (o3_status in ("unsupported",)
               or o4_status in ("unsupported",))
    oracle_complete = bool(ok is not None and not skipped
                           and o1["status"] in ("pass", "fail")
                           and o2["status"] in ("pass", "fail"))
    if fail == "build":
        terminal = "not_run"
    elif ok is None:
        terminal = "not_run"
    elif ok:
        terminal = "pass"
    else:
        terminal = "fail"

    oracle = {
        "built": o1["status"] != "fail" or fail != "build",
        "ran": not o2_fail and o1["status"] == "pass",
        "run_ok": o1["status"] == "pass" and not o2_fail,
        "functional_ok": ok,
        "functional_ok_no_o4": no_o4,
        "terminal_check": terminal,
        "oracle_complete": oracle_complete,
        "layers": layers,
    }
    if not old_o3:
        oracle["o3_tools"] = {
            "shuttle": {"status": shuttle_status, "category": o3_cat
                        if shuttle_status != "pass" else None},
            "miri": {"status": miri_status, "category": o3_cat
                     if miri_status != "pass" else None},
            "no_concurrency": no_conc,
        }
    return oracle


def _baseline_payload(group: dict, plan: dict, rng: random.Random,
                      n_calls: int) -> dict:
    rounds = []
    deadlock = plan.get("fail") == "deadl"
    for call in range(1, n_calls + 1):
        stage = "generate" if call == 1 else (
            "review" if group["arm"] == "REFINE" else "tool_feedback")
        tools: dict = {}
        if group["arm"] == "STATIC":
            lock_fail = (_seed("lockbud", plan["_task"], plan["_rep"],
                               plan["_model"]) % 100) < 45
            tools = {
                "clippy": {"status": "pass", "category": None},
                "lockbud": ({"status": "fail", "category": "ConflictLock"}
                            if lock_fail else {"status": "pass",
                                               "category": None}),
            }
            if plan.get("lockbud_unavailable"):
                tools["lockbud"] = {"status": "unavailable",
                                    "category": "lockbud_failed"}
        elif group["arm"] in ("DYNAMIC", "DYNAMIC_M"):
            tools = {
                "stress": {"status": "pass", "category": None},
                "shuttle": {"status": "fail" if deadlock else "pass",
                            "category": "deadlock" if deadlock else None},
                "miri": {"status": "pass", "category": None},
            }
            if group["arm"] == "DYNAMIC_M":
                tools["monitor"] = {
                    "status": "fail" if plan.get("fail") == "monitor"
                    else "pass",
                    "category": "monitor_fail"
                    if plan.get("fail") == "monitor" else None}
        rounds.append({
            "call": call,
            "stage": stage,
            "reply_kind": "program",
            "version": call,
            "compiled": True,
            "compile": "ok",
            "tools": tools,
            "seeds": {},
            "feedback_sha256": hashlib.sha256(
                f"fb{call}".encode()).hexdigest(),
            "feedback_bytes": rng.randint(0, 9000),
            "truncated": False,
            "compile_wall_ms": rng.randint(100, 2000),
        })
        for tool in rounds[-1]["tools"].values():
            tool["wall_ms"] = rng.randint(1, 300)
    accepted = plan.get("accepted", False)
    return {
        "rounds": rounds,
        "accepted_at_call": n_calls if accepted else None,
        "accept_reason": ("static_clean" if group["arm"] == "STATIC"
                          else "dynamic_monitor_pass"
                          if group["arm"] == "DYNAMIC_M" else "budget_exhausted"),
        "final_version": n_calls,
        "first_round_cache_hit": True,
        "tools_missing": [],
    }


def _build_cell(model: dict, group: dict, task: dict, rep: int, plan: dict,
                spec: dict) -> dict:
    seed = _seed(spec.get("seed", 20260928), model["slug"], group["label"],
                 task["task"], rep)
    rng = random.Random(seed)
    plan = dict(plan)
    plan["_task"] = task["task"]
    plan["_rep"] = rep
    plan["_model"] = model["slug"]
    kind = group["kind"]
    call_budget = spec.get("call_budget", CALL_BUDGET)

    if plan.get("status") == "skipped":
        calls: list[dict] = []
        history: list[dict] = []
        rounds_used = 0
        n = 0
        rust_calls = 0
        rust_attempts = []
    elif kind == "g0":
        n = 1
        calls = [_call(1, "generate", rng, cache_hit=spec.get("cache_hit", False))]
        history = []
        rounds_used = 1
    elif kind == "baseline":
        n = plan.get("calls", call_budget)
        stages = []
        for i in range(1, n + 1):
            stages.append("generate" if i == 1 else (
                "review" if group["arm"] == "REFINE" else "tool_feedback"))
        calls = [_call(i, stages[i - 1], rng,
                       cache_hit=(i == 1 and spec.get("shared_cache", True)))
                 for i in range(1, n + 1)]
        history = [{"call": i, "stage": stages[i - 1], "reply_kind": "program",
                    "version": i} for i in range(1, n + 1)]
        rounds_used = n
    else:  # skel / cir
        skel_calls = plan.get("skel_calls", 1)
        n = plan.get("calls", skel_calls + 1)
        rust_calls = max(0, n - skel_calls)
        stages = []
        for i in range(1, n + 1):
            if i <= skel_calls:
                stages.append("generate" if i == 1 else "feedback")
            else:
                stages.append("rust" if i == skel_calls + 1 else "rust_fix")
        calls = [_call(i, stages[i - 1], rng) for i in range(1, n + 1)]
        history = []
        for i in range(1, skel_calls + 1):
            history.append({"attempt": i, "stage": "verify", "outcome": "PASS",
                            "complete": True, "unmapped": []})
        rust_attempts = []
        for j in range(1, rust_calls + 1):
            rust_attempts.append({
                "call": skel_calls + j, "stage": "rust" if j == 1 else "rust_fix",
                "reply_kind": "program", "compiled": True, "compile": "ok",
                "compile_wall_ms": rng.randint(100, 2000),
            })
        rounds_used = skel_calls

    if plan.get("status") == "skipped":
        oracle = {
            "built": False, "ran": False, "run_ok": False,
            "functional_ok": None, "functional_ok_no_o4": None,
            "terminal_check": "not_run", "oracle_complete": False, "layers": {}}
    else:
        oracle = _oracle(plan, rng)

    accepted = bool(plan.get("accepted", False))
    if plan.get("status") == "error":
        accepted = False

    cell = {
        "schema_version": "skelnet-cell-v1",
        "arm": group["arm"],
        "model": model["display_name"],
        "model_id": model["model_id"],
        "task": task["task"],
        "tier": task.get("tier"),
        "hint": HINT,
        "rep": rep,
        "seed": seed,
        "status": plan.get("status", "ok"),
        "skip_reason": ("no_requirements_text"
                        if plan.get("status") == "skipped" else None),
        "error": plan.get("error"),
        "accepted": accepted,
        "parse_ok": plan.get("parse_ok", accepted or plan.get("ok") is True),
        "check_ok": plan.get("check_ok", accepted or plan.get("ok") is True),
        "rounds_used": rounds_used,
        "history": history,
        "ledger": {},
        "evidence_sufficient": accepted,
        "rust_mode": "llm",
        "calls": calls,
        "budget_used": {
            "calls": len(calls),
            "tokens": sum((c["usage"].get("input") or 0)
                          + (c["usage"].get("output") or 0) for c in calls),
        },
        "oracle": oracle,
    }

    if kind == "baseline":
        cell["baseline"] = _baseline_payload(group, plan, rng, n)
    elif kind in ("skel", "cir"):
        cell["skel_verified"] = accepted
        cell["skel_status"] = "PASS" if accepted else (
            plan.get("skel_status", "FAIL"))
        cell["rust_compiled"] = True if oracle["built"] else None
        cell["rust_calls"] = rust_calls
        cell["rust_attempts"] = rust_attempts
        cell["rust_skipped"] = None
        cell["feedback_mode"] = group.get("feedback_mode", "full")
        cell["rust_when_unverified"] = "last"
        cell["property_ids"] = "keep"
        cell["accepted"] = accepted and cell["rust_compiled"] is True

    return cell


def _assign_outcomes(models, groups, tasks, reps, spec):
    """Exact-count ok assignments so planted effects do not drift.

    Returns ``{(model_slug, label): {(task, rep): True/False/None}}``.  Within
    one (model, group) exactly ``round(rate * n)`` units are ok; groups are
    assigned independently so discordant pairs exist.
    """
    rates = spec.get("rates", {})
    null_rates = spec.get("null_rate") or {}
    assignment: dict = {}
    for model in models:
        for group in groups:
            label = group["label"]
            units = [(t["task"], r) for t in tasks for r in range(reps)]
            units.sort(key=lambda u: _seed("unit", model["slug"], label,
                                           u[0], u[1]))
            n = len(units)
            null_n = round(null_rates.get(label, 0.0) * n)
            chosen: dict = {}
            for task, rep in units[:null_n]:
                chosen[(task, rep)] = None
            live = units[null_n:]
            k = round(rates.get(label, 0.5) * len(live)) if live else 0
            for i, (task, rep) in enumerate(live):
                chosen[(task, rep)] = i < k
            assignment[(model["slug"], label)] = chosen
    return assignment


def _sample_plan(rng: random.Random, spec: dict, label: str,
                 ok: bool | None = None) -> dict:
    features = []
    probs = spec.get("feature_probs") or {}
    for feature in FEATURES:
        p = (probs.get(feature) or {}).get(label, 0.0)
        if rng.random() < p:
            features.append(feature)
    fail = None
    if ok is False:
        choices = [c for c in FAIL_COLUMNS
                   if not ("instrument_unsupported" in features
                           and c in ("design", "monitor"))]
        weights = spec.get("fail_weights") or {}
        w = [weights.get(c, 1.0) for c in choices]
        fail = rng.choices(choices, weights=w, k=1)[0]
    return {
        "status": "ok",
        "ok": ok,
        "fail": fail,
        "features": features,
        "accepted": bool(ok) and rng.random() < 0.9,
        "calls": spec.get("call_budget", CALL_BUDGET),
        "skel_calls": 1,
        "old_o3": rng.random() < 0.4,
    }


def _plan_for(spec: dict, model: dict, group: dict, task: dict, rep: int,
              explicit: dict, assigned: dict) -> dict:
    key = f"{model['slug']}/{group['label']}/{task['task']}/{rep}"
    if key in explicit:
        return dict(explicit[key])
    rng = random.Random(_seed(spec.get("seed", 20260928), "plan",
                              model["slug"], group["label"], task["task"], rep))
    ok = assigned.get((task["task"], rep))
    plan = _sample_plan(rng, spec, group["label"], ok=ok)
    if group["kind"] == "g0":
        plan["calls"] = 1
        plan["skel_calls"] = 0
    elif group["kind"] in ("skel", "cir"):
        plan["skel_calls"] = 1
        plan["calls"] = 1 + rng.randint(1, 2)
    else:
        plan["calls"] = rng.randint(1, spec.get("call_budget", CALL_BUDGET))
    return plan


def _manifest(model: dict, group: dict, spec: dict, tasks: list[dict]) -> dict:
    call_budget = spec.get("call_budget", CALL_BUDGET)
    run_id = spec.get("run_id_prefix", "") + f"{model['slug']}-{_slug(group['label'])}"
    return {
        "run_id": run_id,
        "arm": group["arm"],
        "model": model["display_name"],
        "model_id": model["model_id"],
        "model_policy": {
            "display_name": model["display_name"], "model_id": model["model_id"],
            "channel": model["channel"], "surface": model["surface"],
            "thinking": model["thinking"],
            "reasoning_effort": model["reasoning_effort"],
            "max_output_tokens": 32768, "max_output_tokens_cap": 65536,
            "supports_seed": model["supports_seed"], "stream": False,
        },
        "hint": HINT,
        "stage": spec.get("stage", 2),
        "run_params": {
            "temperature_policy": "provider_default", "temperature": None,
            "seed_policy": "per_cell", "call_budget": call_budget,
            "token_budget": 200000, "hint": HINT,
            "feedback_mode": group.get("feedback_mode", "full"),
            "rust_when_unverified": "last", "property_ids": "keep",
            "max_output_tokens": 32768,
        },
        "tasks": {"pattern": "all",
                  "selected": [t["task"] for t in tasks]},
        "reps": spec.get("reps", 3),
        "rounds": spec.get("rounds", 4),
        "status": "complete",
        "baseline_tools": {"clippy": None, "lockbud": None, "shuttle": None,
                           "missing": []},
    }


def make_runs(root: Path | str, spec: dict) -> list[Path]:
    """Write every run directory described by ``spec`` under ``root``."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    models = spec.get("models") or MODELS
    groups = spec.get("groups")
    if groups is None:
        wanted = spec.get("group_labels")
        groups = [g for g in DEFAULT_GROUPS
                  if wanted is None or g["label"] in wanted]
    tasks = spec.get("tasks") or [
        {"task": "lock-order/abba_2lock", "tier": "L1", "origin": "classic"},
    ]
    reps = spec.get("reps", 3)
    explicit = spec.get("plan") or {}
    assigned = _assign_outcomes(models, groups, tasks, reps, spec)
    paths: list[Path] = []
    for model in models:
        for group in groups:
            run_dir = root / model["slug"] / _slug(group["label"])
            (run_dir / "cells").mkdir(parents=True, exist_ok=True)
            for task in tasks:
                for rep in range(reps):
                    plan = _plan_for(spec, model, group, task, rep, explicit,
                                     assigned[(model["slug"], group["label"])])
                    cell = _build_cell(model, group, task, rep, plan, spec)
                    cell_dir = (run_dir / "cells" / task["task"] / str(rep))
                    cell_dir.mkdir(parents=True, exist_ok=True)
                    _write_json(cell_dir / "result.json", cell)
            manifest = _manifest(model, group, spec, tasks)
            _write_json(run_dir / "MANIFEST.json", manifest)
            paths.append(run_dir)
    return paths


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True,
                               ensure_ascii=False) + "\n", encoding="utf-8")


# ── planted default spec ─────────────────────────────────────────────────

def planted_tasks() -> list[dict]:
    """4 tasks per tier, half classic and half disguised (12 total)."""
    tasks = []
    i = 0
    for tier in ("L1", "L2", "L3"):
        for origin in ("classic", "classic", "disguised", "disguised"):
            tasks.append({"task": f"fam{i % 6}/task{i}", "tier": tier,
                          "origin": origin})
            i += 1
    return tasks


def write_fake_tasks(root: Path | str, tasks: list[dict]) -> None:
    """Write ``benchmarks/tasks/<task>/requirements.json`` under a fake root."""
    root = Path(root) / "benchmarks" / "tasks"
    for task in tasks:
        directory = root / task["task"]
        directory.mkdir(parents=True, exist_ok=True)
        payload = {"tier": task.get("tier")}
        if task.get("origin"):
            payload["origin"] = task["origin"]
        (directory / "requirements.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")


def planted_spec() -> dict:
    tasks = planted_tasks()
    return {
        "seed": 20260928,
        "reps": 3,
        "call_budget": 5,
        "tasks": tasks,
        "rates": {"G0": 0.5, "REFINE": 0.5, "STATIC": 0.5, "DYNAMIC": 0.5,
                  "DYNAMIC_M": 0.7, "SKEL": 0.7, "CIR": 0.6,
                  "SKEL-outcome": 0.55},
        "feature_probs": {
            "instrument_unsupported": {"CIR": 0.4},
            "shuttle_unsupported": {"G0": 0.05, "SKEL": 0.05},
            "no_concurrency": {"DYNAMIC": 0.05},
        },
        "null_rate": {"G0": 0.02},
    }
