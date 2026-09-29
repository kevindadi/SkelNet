"""Round-9 experiment protocol: freeze it, render it, and check it (P1/P2).

``experiments/protocol.json`` is the machine-readable single source of truth;
``experiments/PROTOCOL.md`` is rendered from it and never hand-edited.  Values
are read from the code (params, ``transport.build_registry``, ``PROMPT_ROUTES``
and the prompt assets, the ``RustOracle`` defaults, the seed constants) and the
repository files (task files and ``benchmarks/TIERS.md``) at generation time, so
``protocol check`` fails when any of them drifts from the frozen copy.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import subprocess
import sys
import time
from pathlib import Path

from . import params, prompts, transport
from .backend import repo_root, sha256_file
from .rusttools import seeds as seeds_mod
from .rusttools import shuttle as shuttle_mod

SCHEMA_VERSION = "skelnet-protocol-v1"
DEFAULT_PROTOCOL = "experiments/protocol.json"
DEFAULT_PROTOCOL_MD = "experiments/PROTOCOL.md"

# Shuttle's random scheduler keeps the crate default (``FailAfter(1_000_000)``);
# it is external to this repository, so the fact is fixed here.
RANDOM_MAX_STEPS = 1_000_000

# The concrete Stage-0 selection (D9-3) and group sets (D9-4).
STAGE0_TASKS = [
    "lock-order/abba_2lock",
    "condvar/lost_wakeup_notify_before_wait",
    "atomic-data/atomic_lost_update",
    "lock-order/partial_deadlock_bystander",
]
MAIN_GROUPS = ["G0", "SKEL", "CIR", "REFINE", "STATIC", "DYNAMIC"]
SECONDARY_GROUPS = ["DYNAMIC_M"]
STAGE0_LEDGER = {"max_requests": 800, "max_tokens": 15_000_000}

BENCHMARK_FILES = ("requirements.json", "REQUIREMENTS.h1.md", "contract.json",
                   "gold.skel", "rust/fixed.rs")
ANALYSIS_FAMILY1 = [["SKEL", "G0"], ["SKEL", "REFINE"], ["SKEL", "STATIC"],
                    ["SKEL", "DYNAMIC"]]
ANALYSIS_FAMILY2 = [["CIR", "G0"], ["CIR", "REFINE"], ["CIR", "STATIC"],
                    ["CIR", "DYNAMIC"], ["SKEL", "CIR"], ["SKEL", "DYNAMIC_M"]]
SUCCESS_CRITERIA = [
    "(1) all four main-family Holm p below the O'Brien-Fleming nominal alpha "
    "at the current information fraction",
    "(2) SKEL better than every main baseline in at least 3 of 4 models",
    "(3) positive SKEL - baseline paired delta on L2 union L3",
    "(4) the four sensitivity deltas (O1 & O2 & O3) share the main direction",
    "(5) every main cluster-bootstrap 95% CI lies strictly above zero",
]
DEVIATIONS_POLICY = (
    "Any deviation from this frozen protocol after it is frozen must be "
    "recorded in experiments/DEVIATIONS.md (file header only at freeze time).")


# ── hashing helpers ──────────────────────────────────────────────────────

def _sha_file(path: Path) -> str | None:
    return sha256_file(path) if path.is_file() else None


def _joined_system_sha(assets) -> str:
    text = prompts.PROMPT_SEPARATOR.join(prompts.read_asset(a) for a in assets)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _short_head(root: Path) -> str:
    try:
        proc = subprocess.run(["git", "-C", str(root), "rev-parse", "--short",
                               "HEAD"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):  # pragma: no cover - no git
        return "unknown"
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


# ── protocol construction ────────────────────────────────────────────────

def _models_block() -> list[dict]:
    registry = transport.build_registry()
    out = []
    for spec in transport.experimental_models(registry):
        out.append({
            "display_name": spec.display_name,
            "model_id": spec.model_id,
            "channel": spec.channel,
            "thinking": spec.thinking,
            "reasoning_effort": spec.reasoning_effort,
            "temperature_policy": params.TEMPERATURE_PROVIDER_DEFAULT,
        })
    return out


def _run_params_block() -> dict:
    return {
        "call_budget": params.DEFAULT_CALL_BUDGET,
        "token_budget": params.DEFAULT_TOKEN_BUDGET,
        "max_output_tokens": params.DEFAULT_MAX_OUTPUT_TOKENS,
        "max_output_tokens_cap": params.DEFAULT_MAX_OUTPUT_TOKENS_CAP,
        "seed_policy": params.SEED_PER_CELL,
        "temperature_policy": params.TEMPERATURE_PROVIDER_DEFAULT,
        "hint": params.DEFAULT_HINT,
    }


def _routes_block() -> dict:
    out: dict = {}
    for (arm, stage), assets in sorted(prompts.PROMPT_ROUTES.items()):
        out.setdefault(arm, {})[stage] = {
            "assets": list(assets),
            "sha256": [_sha_file(prompts.PROMPT_ASSET_DIR / a) for a in assets],
            "system_sha256": _joined_system_sha(assets),
        }
    return out


def _arms_block() -> dict:
    return {"main": list(MAIN_GROUPS), "secondary": list(SECONDARY_GROUPS),
            "routes": _routes_block()}


def _oracle_default(name: str):
    """One ``RustOracle.__init__`` default, read from the live signature."""
    from .oracle import RustOracle
    signature = inspect.signature(RustOracle.__init__)
    return signature.parameters[name].default


def _oracle_block() -> dict:
    return {
        "stress_runs": _oracle_default("stress_runs"),
        "stress_timeout": _oracle_default("stress_timeout"),
        "shuttle_iterations": _oracle_default("shuttle_iterations"),
        "shuttle_depth": _oracle_default("shuttle_depth"),
        "monitor_runs": _oracle_default("monitor_runs"),
        "pct_max_steps": shuttle_mod.PCT_MAX_STEPS,
        "random_max_steps": RANDOM_MAX_STEPS,
        "oracle_shuttle_seed": seeds_mod.ORACLE_SHUTTLE_SEED,
        "oracle_miri_seed_start": seeds_mod.ORACLE_MIRI_SEED_START,
        "oracle_miri_seed_count": seeds_mod.ORACLE_MIRI_SEED_COUNT,
    }


def _task_rel_dirs(root: Path) -> list[str]:
    base = root / "benchmarks" / "tasks"
    if not base.is_dir():
        return []
    return sorted(str(p.parent.relative_to(base))
                  for p in base.glob("*/*/contract.json"))


def _tier_of(task_dir: Path) -> dict:
    path = task_dir / "requirements.json"
    tier = tier_source = None
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        if isinstance(data.get("tier"), str):
            tier = data["tier"]
        if isinstance(data.get("tier_source"), str):
            tier_source = data["tier_source"]
    return {"tier": tier, "tier_source": tier_source}


def _benchmark_block(root: Path) -> dict:
    base = root / "benchmarks" / "tasks"
    tasks = []
    for rel in _task_rel_dirs(root):
        task_dir = base / rel
        entry = {"task": rel, **_tier_of(task_dir), "sha256": {}}
        for name in BENCHMARK_FILES:
            entry["sha256"][name] = _sha_file(task_dir / name)
        tasks.append(entry)
    tiers = root / "benchmarks" / "TIERS.md"
    return {"tiers_sha256": _sha_file(tiers), "tasks": tasks}


def _stages_block() -> dict:
    models = [spec.model_id for spec in
              transport.experimental_models(transport.build_registry())]
    return {
        "0": {
            "tasks": list(STAGE0_TASKS),
            "groups": list(MAIN_GROUPS),
            "models": models,
            "reps": 1,
            "cells": 100,
            "secondary_smoke": {"arm": "DYNAMIC_M",
                                "task": "lock-order/abba_2lock", "reps": 1},
            "expected_paired_units": 16,
            "ledger_limits": dict(STAGE0_LEDGER),
        },
        "1": {
            "tasks": None,
            "groups": list(MAIN_GROUPS),
            "models": models,
            "reps": 3,
            "expected_paired_units": 288,
            "ledger_limits": None,
            "note": "task selection fixed by the experiment plan (coordinator)",
        },
        "2": {
            "tasks": None,
            "groups": list(MAIN_GROUPS) + list(SECONDARY_GROUPS),
            "models": models,
            "reps": None,
            "expected_paired_units": 528,
            "ledger_limits": None,
            "note": "task selection fixed by the experiment plan (coordinator)",
        },
        "3": {
            "tasks": None,
            "groups": list(MAIN_GROUPS) + list(SECONDARY_GROUPS),
            "models": models,
            "reps": None,
            "expected_paired_units": 880,
            "ledger_limits": None,
            "note": "task selection fixed by the experiment plan (coordinator)",
        },
    }


def _analysis_block() -> dict:
    from .stop_check import FUTILITY_MARGIN
    from .report import ReportContext
    return {
        "family1": [list(pair) for pair in ANALYSIS_FAMILY1],
        "family2": [list(pair) for pair in ANALYSIS_FAMILY2],
        "multiplicity": "holm",
        "bootstrap": ReportContext.bootstrap,
        "seed": ReportContext.seed,
        "alpha": 0.05,
        "sided": 2,
        "planned_units": ReportContext.planned_units,
        "futility_margin": FUTILITY_MARGIN,
        "success_criteria": list(SUCCESS_CRITERIA),
    }


def build_protocol(*, root: Path | None = None, fixed_time: str | None = None,
                   commit: str | None = None) -> dict:
    """Assemble the protocol document from the current code and repository."""
    root = Path(root) if root is not None else repo_root()
    frozen_at = fixed_time if fixed_time is not None else _iso_now()
    return {
        "schema_version": SCHEMA_VERSION,
        "frozen_at_commit": commit if commit is not None else _short_head(root),
        "frozen_at": frozen_at,
        "models": _models_block(),
        "run_params": _run_params_block(),
        "arms": _arms_block(),
        "oracle": _oracle_block(),
        "benchmark": _benchmark_block(root),
        "stages": _stages_block(),
        "analysis": _analysis_block(),
        "deviations_policy": DEVIATIONS_POLICY,
    }


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── checking ─────────────────────────────────────────────────────────────

CHECKED_FIELDS = ("schema_version", "models", "run_params", "arms", "oracle",
                  "benchmark", "stages", "analysis", "deviations_policy")


def _diff(path: str, frozen, current, out: list[dict]) -> None:
    if isinstance(frozen, dict) and isinstance(current, dict):
        for key in sorted(set(frozen) | set(current)):
            _diff(f"{path}.{key}" if path else str(key),
                  frozen.get(key), current.get(key), out)
        return
    if isinstance(frozen, list) and isinstance(current, list):
        if len(frozen) != len(current):
            out.append({"field": path, "frozen": frozen, "current": current})
            return
        for index, (left, right) in enumerate(zip(frozen, current)):
            _diff(f"{path}[{index}]", left, right, out)
        return
    if frozen != current:
        out.append({"field": path, "frozen": frozen, "current": current})


def check_protocol(doc: dict, root: Path | None = None) -> list[dict]:
    """Return a list of ``{field, frozen, current}`` mismatches (empty is ok)."""
    root = Path(root) if root is not None else repo_root()
    expected = build_protocol(root=root)
    mismatches: list[dict] = []
    for field in CHECKED_FIELDS:
        _diff(field, doc.get(field), expected.get(field), mismatches)
    return mismatches


# ── rendering ────────────────────────────────────────────────────────────

def _bool(value) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return str(value)


def render_markdown(doc: dict, protocol_sha: str) -> str:
    lines: list[str] = []
    lines.append("# SkelNet experiment protocol (frozen)")
    lines.append("")
    lines.append("> This file is generated from `protocol.json` by "
                 "`python -m skelnet protocol render`. Do not edit it by hand.")
    lines.append("")
    lines.append(f"- `protocol.json` sha256: `{protocol_sha}`")
    lines.append(f"- schema: `{doc.get('schema_version')}`")
    lines.append(f"- frozen at commit: `{doc.get('frozen_at_commit')}`")
    lines.append(f"- frozen at: `{doc.get('frozen_at')}`")
    lines.append("")

    lines.append("## Models")
    lines.append("")
    lines.append("| display name | model id | channel | thinking | reasoning effort | temperature |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for model in doc.get("models", []):
        lines.append(
            f"| {model['display_name']} | `{model['model_id']}` | "
            f"`{model['channel']}` | {_bool(model['thinking'])} | "
            f"{model['reasoning_effort'] or '--'} | {model['temperature_policy']} |")
    lines.append("")

    lines.append("## Run parameters")
    lines.append("")
    lines.append("| field | value |")
    lines.append("| --- | --- |")
    for key in sorted(doc.get("run_params", {})):
        lines.append(f"| {key} | {doc['run_params'][key]} |")
    lines.append("")

    lines.append("## Arms and prompt routes")
    lines.append("")
    lines.append("Main groups: " + ", ".join(doc["arms"]["main"]) + ".")
    lines.append("")
    lines.append("Secondary groups: " + ", ".join(doc["arms"]["secondary"]) + ".")
    lines.append("")
    lines.append("| arm | stage | assets | system sha256 |")
    lines.append("| --- | --- | --- | --- |")
    for arm in sorted(doc["arms"]["routes"]):
        for stage in sorted(doc["arms"]["routes"][arm]):
            entry = doc["arms"]["routes"][arm][stage]
            assets = ", ".join(f"`{a}`" for a in entry["assets"])
            lines.append(f"| {arm} | {stage} | {assets} | "
                         f"`{entry['system_sha256']}` |")
    lines.append("")

    lines.append("## Oracle")
    lines.append("")
    lines.append("| field | value |")
    lines.append("| --- | --- |")
    for key in sorted(doc.get("oracle", {})):
        lines.append(f"| {key} | {doc['oracle'][key]} |")
    lines.append("")

    lines.append("## Benchmark")
    lines.append("")
    lines.append(f"`benchmarks/TIERS.md` sha256: `{doc['benchmark']['tiers_sha256']}`")
    lines.append("")
    lines.append("| task | tier | tier source |")
    lines.append("| --- | --- | --- |")
    for task in doc["benchmark"]["tasks"]:
        lines.append(f"| {task['task']} | {task['tier'] or '--'} | "
                     f"{task['tier_source'] or '--'} |")
    lines.append("")

    lines.append("## Stages")
    lines.append("")
    for name in sorted(doc.get("stages", {})):
        stage = doc["stages"][name]
        lines.append(f"### Stage {name}")
        lines.append("")
        tasks = stage.get("tasks")
        lines.append("- tasks: " + ("(experiment plan)" if tasks is None
                                    else ", ".join(tasks)))
        lines.append("- groups: " + ", ".join(stage.get("groups", [])))
        lines.append("- models: " + ", ".join(stage.get("models", [])))
        lines.append(f"- reps: {stage.get('reps')}")
        lines.append(f"- expected paired units: {stage.get('expected_paired_units')}")
        limits = stage.get("ledger_limits")
        lines.append("- ledger limits: " + ("--" if limits is None
                                            else json.dumps(limits, sort_keys=True)))
        if stage.get("secondary_smoke"):
            smoke = stage["secondary_smoke"]
            lines.append(f"- secondary smoke: {smoke['arm']} x {smoke['task']} "
                         f"x reps={smoke['reps']}")
        if stage.get("note"):
            lines.append("- note: " + stage["note"])
        lines.append("")

    lines.append("## Analysis")
    lines.append("")
    analysis = doc.get("analysis", {})
    family1 = " ".join(f"({a} vs {b})" for a, b in analysis.get("family1", []))
    family2 = " ".join(f"({a} vs {b})" for a, b in analysis.get("family2", []))
    lines.append(f"- family 1: {family1}")
    lines.append(f"- family 2: {family2}")
    lines.append(f"- multiplicity: {analysis.get('multiplicity')}")
    lines.append(f"- bootstrap: {analysis.get('bootstrap')} "
                 f"(seed {analysis.get('seed')})")
    lines.append(f"- alpha: {analysis.get('alpha')} "
                 f"({analysis.get('sided')}-sided)")
    lines.append(f"- planned units: {analysis.get('planned_units')}")
    lines.append(f"- futility margin: {analysis.get('futility_margin')}")
    lines.append("")
    lines.append("Success criteria:")
    lines.append("")
    for criterion in analysis.get("success_criteria", []):
        lines.append(f"- {criterion}")
    lines.append("")

    lines.append("## Deviations policy")
    lines.append("")
    lines.append(doc.get("deviations_policy", ""))
    lines.append("")
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────

def register(sub) -> None:
    parser = sub.add_parser("protocol", help="freeze / render / check the protocol")
    inner = parser.add_subparsers(dest="protocol_cmd", required=True)

    build = inner.add_parser("build", help="write protocol.json from the code")
    build.add_argument("--out", default=DEFAULT_PROTOCOL)
    build.add_argument("--root", default=None)
    build.add_argument("--fixed-time", default=None)
    build.add_argument("--commit", default=None)
    build.set_defaults(func=cmd_build)

    render = inner.add_parser("render", help="render PROTOCOL.md from protocol.json")
    render.add_argument("--protocol", default=DEFAULT_PROTOCOL)
    render.add_argument("--out", default=DEFAULT_PROTOCOL_MD)
    render.set_defaults(func=cmd_render)

    check = inner.add_parser("check", help="compare protocol.json to the code")
    check.add_argument("--protocol", default=DEFAULT_PROTOCOL)
    check.add_argument("--root", default=None)
    check.set_defaults(func=cmd_check)


def _resolve(path_text: str) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else repo_root() / path


def cmd_build(args) -> int:
    root = Path(args.root) if args.root else repo_root()
    doc = build_protocol(root=root, fixed_time=args.fixed_time,
                         commit=args.commit)
    out = _resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"wrote {out}")
    return 0


def cmd_render(args) -> int:
    path = _resolve(args.protocol)
    if not path.is_file():
        print(f"protocol render: no protocol at {args.protocol}", file=sys.stderr)
        return 2
    raw = path.read_bytes()
    try:
        doc = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        print(f"protocol render: {exc}", file=sys.stderr)
        return 2
    digest = hashlib.sha256(raw).hexdigest()
    out = _resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(doc, digest), encoding="utf-8")
    print(f"wrote {out}")
    return 0


def cmd_check(args) -> int:
    path = _resolve(args.protocol)
    if not path.is_file():
        print(f"protocol check: no protocol at {args.protocol}", file=sys.stderr)
        return 2
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"protocol check: {exc}", file=sys.stderr)
        return 2
    root = Path(args.root) if args.root else repo_root()
    mismatches = check_protocol(doc, root)
    if not mismatches:
        print("protocol check: ok")
        return 0
    print(f"protocol check: {len(mismatches)} mismatch(es)")
    for item in mismatches:
        print(f"- {item['field']}: frozen={item['frozen']!r} "
              f"current={item['current']!r}")
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(0)
