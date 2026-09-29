"""``python -m skelnet`` command line: run / eval / report."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import prompts
from .audit import AuditLog
from .backend import Backend, repo_root, sha256_file
from .budget import BudgetLedger, CellBudget
from .cache import CachedClient, ResponseCache
from .models import normalize_token_usage
from .oracle import RustOracle, oracle_result_dict, repo_toolchain_channel
from .params import params_for_model, seed_for
from .pipeline import (dumps, run_cir_cell, run_g0_cell, run_skel_cell)
from .providers import CandidateResponse
from .requirements_render import RequirementsMissing, render_requirements
from .rusttools.runner import ToolRunner
from .schema import validate_cell
from .transport import (BudgetExceeded, ModelIdentityError, TransportError,
                        build_registry, experimental_models, resolve_model)


def _task_dirs(root: Path) -> list[Path]:
    base = root / "benchmarks" / "tasks"
    return sorted(p.parent for p in base.glob("*/*/contract.json"))


def _select_tasks(root: Path, pattern: str) -> list[Path]:
    dirs = _task_dirs(root)
    if pattern in (None, "", "all"):
        return dirs
    out = []
    for d in dirs:
        rel = str(d.relative_to(root / "benchmarks" / "tasks"))
        if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(d.name, pattern):
            out.append(d)
    return out


def select_task_patterns(root: Path, pattern: str | None) -> tuple[list[Path], list[str]]:
    """``all`` or a comma-separated union of fnmatch patterns.

    Returns task directories in directory order, and the patterns that matched
    nothing. An empty repository makes ``all`` unmatched. ``_select_tasks``
    stays single-pattern.
    """
    text = "all" if pattern in (None, "") else str(pattern)
    universe = _select_tasks(root, "all")
    if text == "all":
        return (universe, []) if universe else ([], ["all"])
    parts = [part.strip() for part in text.split(",") if part.strip()]
    if not parts:
        return [], [text]
    order = {task: index for index, task in enumerate(universe)}
    chosen: dict[Path, int] = {}
    unmatched: list[str] = []
    for part in parts:
        hits = _select_tasks(root, part)
        if not hits:
            unmatched.append(part)
            continue
        for task in hits:
            chosen.setdefault(task, order.get(task, 10**9))
    ordered = [task for task, _index in sorted(chosen.items(), key=lambda item: item[1])]
    return ordered, unmatched


def _report_unmatched_patterns(unmatched: list[str], pattern: str) -> None:
    names = unmatched or [str(pattern)]
    print("unmatched task patterns: " + ", ".join(names), file=sys.stderr)


def read_terminal(task_dir: Path, hint: str = "h1") -> str | None:
    """The required terminating stdout line for a task.

    Canonical source: ``requirements.json``. With ``hint == "h0"`` the
    ``terminal`` field is returned; otherwise ``terminal_v2`` is preferred when
    present. Tasks without a ``requirements.json`` (the boundary tasks) have no
    terminal line, recorded as ``terminal_check: "absent"`` and never a pass.
    """
    reqs = Path(task_dir) / "requirements.json"
    if not reqs.exists():
        return None
    try:
        data = json.loads(reqs.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    key = "terminal" if hint == "h0" else "terminal_v2"
    terminal = data.get(key)
    if not (isinstance(terminal, str) and terminal):
        terminal = data.get("terminal")
    return terminal if isinstance(terminal, str) and terminal else None


def _budget(arm: str, tasks: int, reps: int, rounds: int,
            rust_mode: str = "llm", call_budget: int | None = None) -> dict:
    if call_budget is None:
        if arm == "G0":
            per_rep = 1
        else:
            per_rep = rounds + (1 if rust_mode == "llm" else 0)
    elif arm == "G0":
        per_rep = 1
    elif arm in ("SKEL", "CIR") and rust_mode == "codegen":
        # The skeleton stage gets at most min(rounds, B-1); codegen has no
        # Rust LLM stage, so the same skeleton rule applies.
        per_rep = min(rounds, call_budget - 1)
    else:
        # SKEL/CIR (llm) and every round-4 baseline arm: the cell budget.
        per_rep = call_budget
    per_task = reps * per_rep
    return {"arm": arm, "tasks": tasks, "reps": reps, "rounds": rounds,
            "rust_mode": rust_mode, "call_budget": call_budget,
            "requests": tasks * per_task, "requests_per_task": per_task}


def _asset_sha(asset: str) -> str | None:
    path = prompts.PROMPT_ASSET_DIR / asset
    return sha256_file(path)


def _joined_system_prompt(assets) -> str:
    return prompts.PROMPT_SEPARATOR.join(prompts.read_asset(a) for a in assets)


def _system_sha(assets) -> str:
    return hashlib.sha256(_joined_system_prompt(assets).encode("utf-8")).hexdigest()


def default_oracle_factory(*, timeout: float, runner=None):
    """The real per-task oracle factory used when none is injected.

    Kept as a module-level function so the default path (the one real runs take)
    is testable: the terminal line must reach the oracle.
    """
    def factory(task_dir, terminal):
        return RustOracle(terminal=terminal, timeout=timeout, runner=runner,
                          task_dir=task_dir)
    return factory


def _is_ancestor(ancestor: Path, descendant: Path) -> bool:
    """True when `ancestor` is `descendant` or a strict ancestor of it."""
    try:
        descendant.relative_to(ancestor)
        return True
    except ValueError:
        return False


def _unsafe_to_clear(out: Path) -> str | None:
    """A human reason why `out` must not be recursively deleted, or None."""
    if out.is_symlink():
        return "it is a symlink"
    resolved = out.resolve()
    protected = {
        "the repository": repo_root(),
        "the current directory": Path.cwd(),
        "the home directory": Path.home(),
        "the filesystem root": Path(resolved.anchor),
    }
    for label, path in protected.items():
        try:
            target = path.resolve()
        except OSError:  # pragma: no cover - unresolvable protected path
            target = path
        if resolved == target:
            return f"it is {label}"
        # `out` is an ancestor of a protected path (so clearing it would
        # destroy that path).
        if _is_ancestor(resolved, target):
            return f"it is an ancestor of {label}"
    return None


def _prepare_out(out: Path, *, force: bool) -> None:
    """Validate/clear the output directory before a run.

    `--force` only clears a *previous run directory* (one that carries a
    MANIFEST.json) and refuses the repository, the current directory, the home
    directory, the filesystem root, symlinks, and their ancestors.
    """
    out = Path(out)
    if (out.exists() or out.is_symlink()) and not out.is_dir():
        raise SystemExit(f"output path {out} exists and is not a directory")
    if not out.exists() or not any(out.iterdir()):
        out.mkdir(parents=True, exist_ok=True)
        return
    if not force:
        raise SystemExit(
            f"output directory {out} is not empty; pass --force to overwrite")
    reason = _unsafe_to_clear(out)
    if reason:
        raise SystemExit(f"refusing to clear {out}: {reason}")
    if not (out / "MANIFEST.json").exists():
        raise SystemExit(
            f"refusing to clear {out}: no MANIFEST.json (not a previous run directory)")
    shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)


def cmd_run(args: argparse.Namespace, *, client_factory=None,
            oracle_factory=None, oracle_runner=None) -> int:
    if args.arm == "G0" and args.rust_mode == "codegen":
        raise SystemExit(
            "--arm G0 writes Rust directly and has no codegen stage; "
            "use --rust-mode llm")
    if getattr(args, "replay_mode", "key") == "sequence" and not args.replay_from:
        raise SystemExit("--replay-mode sequence requires --replay-from")
    root = repo_root()
    tasks, unmatched = select_task_patterns(root, args.tasks)
    if unmatched or not tasks:
        _report_unmatched_patterns(unmatched, args.tasks)
        return 2
    spec = resolve_model(build_registry(), args.model)
    run_params = _run_params(args, spec)
    if args.stage in (1, 2, 3) and run_params.hint != "h1" \
            and not getattr(args, "allow_nonprotocol_hint", False):
        raise SystemExit(
            "--stage 1, 2, or 3 requires hint h1 (plan D10); "
            "pass --allow-nonprotocol-hint to override")
    budget = _budget(args.arm, len(tasks), args.reps, args.rounds,
                     args.rust_mode, run_params.call_budget)
    if args.dry_run:
        routes = prompts.routes_for_arm(args.arm)
        first_task = (str(tasks[0].relative_to(root / "benchmarks" / "tasks"))
                      if tasks else None)
        print(json.dumps({
            **budget,
            "dry_run": True,
            "hint_source": getattr(args, "hint_source", "default"),
            "requirements_missing": _requirements_missing(root, tasks, run_params.hint),
            "run_params": run_params.to_dict(),
            "sample_seed": ({"task": first_task, "rep": 0,
                             "seed": seed_for(first_task, 0)} if first_task else None),
            "model_policy": _model_policy(spec),
            "model_policies": [_model_policy_entry(s, run_params)
                               for s in experimental_models()],
            "prompt_routes": {
                stage: {
                    "assets": list(assets),
                    "sha256": [_asset_sha(a) for a in assets],
                    "system_sha256": _system_sha(assets),
                }
                for stage, assets in routes.items()
            },
            "prompts": prompts.prompt_asset_record(),
        }, indent=2))
        return 0

    _preflight_baseline_tools(args)
    _preflight_hint_requirements(run_params, tasks)
    out = Path(args.out)
    if args.resume:
        _check_resume(out, args, run_params)
    else:
        _prepare_out(out, force=args.force)
    started_at = time.time()
    audit = AuditLog(out / "audit.jsonl", raw_dir=out / "raw")
    backend = Backend(timeout=args.timeout)
    ledger = BudgetLedger(args.budget_file, stage=args.stage)
    manifest = _build_manifest(out, args, backend, tasks, started_at, None,
                               budget, spec, run_params)
    manifest["status"] = "running"
    _write_manifest(out, manifest)
    if oracle_factory is None:
        oracle_factory = default_oracle_factory(timeout=args.timeout,
                                                runner=oracle_runner)
    provider = _build_provider(args, audit, out, spec, run_params, ledger,
                               client_factory=client_factory)
    compile_tools = ToolRunner(runner=oracle_runner)
    summary: dict = {"run_id": out.name, "arm": args.arm, "model": args.model,
                     "budget": budget, "cells": []}
    for task_dir in tasks:
        task = str(task_dir.relative_to(root / "benchmarks" / "tasks"))
        tier = _task_tier(task_dir)
        contract = task_dir / "contract.json"
        try:
            requirements = render_requirements(task_dir, run_params.hint)
        except RequirementsMissing:
            for rep in range(args.reps):
                workdir = out / "cells" / task / str(rep)
                if args.resume and (workdir / "result.json").exists():
                    continue
                workdir.mkdir(parents=True, exist_ok=True)
                cell = _skipped_cell(args, spec, run_params, task, tier, rep)
                _write_cell(workdir, cell)
                summary["cells"].append(cell)
            continue
        terminal = read_terminal(task_dir, run_params.hint)
        task_oracle = oracle_factory(task_dir, terminal)
        for rep in range(args.reps):
            workdir = out / "cells" / task / str(rep)
            if args.resume and (workdir / "result.json").exists():
                continue
            workdir.mkdir(parents=True, exist_ok=True)
            if hasattr(provider, "set_cell"):
                provider.set_cell(f"{task}/{rep}", task, rep)
            base = _base_cell(args, spec, run_params, task, tier, rep)
            try:
                if args.arm in prompts.BASELINE_ARMS:
                    if args.rust_mode == "codegen":
                        raise SystemExit(
                            f"--arm {args.arm} writes Rust directly and has no "
                            "codegen stage; use --rust-mode llm")
                    from .baselines import run_baseline_cell
                    cell = run_baseline_cell(
                        arm=args.arm, task=task, requirements=requirements,
                        task_dir=task_dir, terminal=terminal, provider=provider,
                        oracle=task_oracle, workdir=workdir, replicate=rep,
                        run_params=run_params, tools=compile_tools,
                        tools_missing=_missing_baseline_tools(args),
                        miri_seed_count=args.feedback_miri_seeds,
                        timeout=args.timeout)
                elif args.arm == "G0":
                    cell = run_g0_cell(task=task, requirements=requirements,
                                       provider=provider, oracle=task_oracle,
                                       workdir=workdir, replicate=rep,
                                       tools=compile_tools)
                elif args.arm == "SKEL":
                    cell = run_skel_cell(task=task, requirements=requirements,
                                         contract_path=contract, provider=provider,
                                         backend=backend, oracle=task_oracle,
                                         workdir=workdir, rounds=args.rounds,
                                         replicate=rep, rust_mode=args.rust_mode,
                                         call_budget=run_params.call_budget,
                                         rust_when_unverified=run_params.rust_when_unverified,
                                         feedback_mode=run_params.feedback_mode,
                                         property_ids=run_params.property_ids,
                                         tools=compile_tools)
                elif args.arm == "CIR":
                    cell = run_cir_cell(task=task, requirements=requirements,
                                        contract_path=contract, provider=provider,
                                        backend=backend, oracle=task_oracle,
                                        workdir=workdir, rounds=args.rounds,
                                        replicate=rep, rust_mode=args.rust_mode,
                                        call_budget=run_params.call_budget,
                                        rust_when_unverified=run_params.rust_when_unverified,
                                        feedback_mode=run_params.feedback_mode,
                                        property_ids=run_params.property_ids,
                                        tools=compile_tools)
                else:
                    raise SystemExit(f"unknown arm {args.arm!r}")
                _write_artifacts(workdir, cell)
                data = _merge_cell(base, cell, provider, run_params)
            except BudgetExceeded as exc:
                manifest["status"] = "budget_exhausted"
                manifest["ended_at"] = time.time()
                manifest["budget_error"] = str(exc)
                _write_manifest(out, manifest)
                _write_summary(out, summary)
                print(f"budget exhausted: {exc}")
                return 1
            except ModelIdentityError as exc:
                manifest["status"] = "failed"
                manifest["failure"] = "model_identity"
                manifest["failure_error"] = str(exc)
                manifest["ended_at"] = time.time()
                _write_manifest(out, manifest)
                _write_summary(out, summary)
                print(f"model identity mismatch: {exc}")
                return 1
            except Exception as exc:  # noqa: BLE001 - isolate cell failures
                data = _error_cell(args, spec, run_params, task, tier, rep, exc)
            _write_cell(workdir, data)
            summary["cells"].append(data)
    ended_at = time.time()
    manifest["ended_at"] = ended_at
    manifest["status"] = "complete"
    _write_manifest(out, manifest)
    _write_summary(out, summary)
    print(f"wrote {out}")
    return 0


def _run_params(args: argparse.Namespace, spec):
    temperature = args.temperature
    if args.temperature_policy == "fixed" and temperature is None:
        raise SystemExit("--temperature-policy fixed requires --temperature")
    if args.temperature_policy != "fixed" and temperature is not None:
        raise SystemExit("--temperature is only allowed with --temperature-policy fixed")
    # The method knobs only apply to SKEL/CIR (property ids also to DYNAMIC_M).
    if args.arm not in ("SKEL", "CIR"):
        if getattr(args, "feedback_mode", "full") != "full":
            raise SystemExit(f"--feedback-mode is only valid for SKEL/CIR (arm {args.arm})")
        if getattr(args, "rust_when_unverified", "last") != "last":
            raise SystemExit(
                f"--rust-when-unverified is only valid for SKEL/CIR (arm {args.arm})")
    overrides = dict(
        temperature_policy=args.temperature_policy,
        temperature=(temperature if args.temperature_policy == "fixed" else None),
        seed_policy=args.seed_policy, call_budget=args.call_budget,
        token_budget=args.token_budget, hint=_resolved_hint(args),
        feedback_mode=getattr(args, "feedback_mode", "full"),
        rust_when_unverified=getattr(args, "rust_when_unverified", "last"),
        property_ids=getattr(args, "property_ids", "keep"))
    # None means "use the registry's per-model value".
    if args.max_output_tokens is not None:
        overrides["max_output_tokens"] = args.max_output_tokens
    return params_for_model(spec, **overrides)


def _model_policy(spec) -> dict:
    return {
        "display_name": spec.display_name, "model_id": spec.model_id,
        "channel": spec.channel, "surface": spec.surface,
        "thinking": spec.thinking, "reasoning_effort": spec.reasoning_effort,
        "max_output_tokens": spec.max_output_tokens,
        "max_output_tokens_cap": spec.max_output_tokens_cap,
        "supports_seed": spec.supports_seed, "stream": spec.stream,
    }


def _model_policy_entry(spec, run_params) -> dict:
    return {**_model_policy(spec),
            "temperature_sent": run_params.temperature_policy == "fixed"}


def _task_tier(task_dir: Path) -> str | None:
    reqs = task_dir / "requirements.json"
    if not reqs.exists():
        return None
    try:
        data = json.loads(reqs.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    tier = data.get("tier")
    return tier if isinstance(tier, str) else None


def _check_resume(out: Path, args, run_params) -> None:
    manifest_path = out / "MANIFEST.json"
    if not manifest_path.exists():
        raise SystemExit(f"--resume requires an existing run at {out}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("arm") != args.arm or manifest.get("model") != args.model:
        raise SystemExit("--resume: arm/model do not match the existing run")
    if manifest.get("rounds") != args.rounds or manifest.get("reps") != args.reps:
        raise SystemExit("--resume: rounds/reps do not match the existing run")
    if manifest.get("run_params") != run_params.to_dict():
        raise SystemExit("--resume: RunParams do not match the existing run")
    selected = (manifest.get("tasks") or {}).get("selected")
    selected_now, unmatched = select_task_patterns(repo_root(), args.tasks)
    if unmatched or not selected_now:
        _report_unmatched_patterns(unmatched, args.tasks)
        raise SystemExit(2)
    want = [str(t.relative_to(repo_root() / "benchmarks" / "tasks"))
            for t in selected_now]
    if selected != want:
        raise SystemExit("--resume: tasks do not match the existing run")
    recorded = manifest.get("baseline_tools")
    current = _baseline_tools_snapshot(args)
    if recorded != current:
        raise SystemExit("--resume: baseline_tools do not match the existing run")


def _write_summary(out: Path, summary: dict) -> None:
    (out / "SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out / "REPORT.md").write_text(_report_markdown([summary]), encoding="utf-8")


def _base_cell(args, spec, run_params, task, tier, rep) -> dict:
    return {
        "schema_version": "skelnet-cell-v1",
        "arm": args.arm, "model": args.model, "model_id": spec.model_id,
        "task": task, "tier": tier, "hint": run_params.hint, "rep": rep,
        "seed": seed_for(task, rep), "status": "ok", "skip_reason": None,
        "error": None, "accepted": False, "parse_ok": False, "check_ok": False,
        "rounds_used": 0, "history": [], "ledger": {},
        "evidence_sufficient": False, "rust_mode": args.rust_mode,
        "calls": [], "budget_used": {"calls": 0, "tokens": 0},
        "oracle": {"built": False, "ran": False, "run_ok": False,
                   "functional_ok": None, "terminal_check": "not_run"},
    }


def _skipped_cell(args, spec, run_params, task, tier, rep) -> dict:
    cell = _base_cell(args, spec, run_params, task, tier, rep)
    cell["status"] = "skipped"
    cell["skip_reason"] = "no_requirements_text"
    return cell


def _error_cell(args, spec, run_params, task, tier, rep, exc) -> dict:
    cell = _base_cell(args, spec, run_params, task, tier, rep)
    cell["status"] = "error"
    cell["error"] = f"{type(exc).__name__}: {exc}"
    return cell


def _merge_cell(base: dict, cell, provider, run_params) -> dict:
    """Merge a pipeline CellResult onto the D1 base cell (no field whitelist)."""
    data = dict(base)
    pipeline = json.loads(dumps(cell))
    for key, value in pipeline.items():
        if key == "replicate":
            continue
        if key == "oracle":
            if value is not None:
                data["oracle"] = value
            continue
        data[key] = value
    data["rep"] = pipeline.get("replicate", base["rep"])
    if provider is not None:
        data["calls"] = list(getattr(provider, "calls", []))
        if getattr(provider, "cell_budget", None) is not None:
            data["budget_used"] = provider.cell_budget.snapshot()
    return data


def _write_cell(workdir: Path, data: dict) -> None:
    errors = validate_cell(data)
    if errors:
        raise RuntimeError(f"invalid cell schema at {workdir}: {errors}")
    (workdir / "result.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_artifacts(workdir: Path, cell) -> None:
    rust = getattr(cell, "rust", None)
    if rust:
        (workdir / "candidate.rs").write_text(rust, encoding="utf-8")
    trace = getattr(cell, "cir_trace", None)
    if trace:
        (workdir / "cir_trace.rs").write_text(trace, encoding="utf-8")


def _git(args: list[str]) -> str:
    try:
        proc = subprocess.run(["git", "-C", str(repo_root()), *args],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def _tool_version(command: str) -> str | None:
    env = dict(os.environ)
    channel = repo_toolchain_channel()
    if channel:
        env["RUSTUP_TOOLCHAIN"] = channel
    try:
        proc = subprocess.run([command, "-V"], capture_output=True, text=True,
                              timeout=30, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def _build_manifest(out: Path, args: argparse.Namespace, backend: Backend,
                    tasks: list[Path], started_at: float,
                    ended_at: float | None, budget: dict | None = None,
                    spec=None, run_params=None) -> dict:
    tasks_root = repo_root() / "benchmarks" / "tasks"
    return {
        "run_id": out.name,
        "budget": budget,
        "git_sha": _git(["rev-parse", "HEAD"]).strip(),
        "git_dirty": bool(_git(["status", "--porcelain"]).strip()),
        "binaries": {
            "skelnet": sha256_file(backend.skelnet),
            "concir-backend": sha256_file(backend.concir),
        },
        "prompts": prompts.prompt_asset_record(),
        "model": args.model,
        "model_id": getattr(spec, "model_id", None),
        "channel": getattr(spec, "channel", None),
        "model_policy": _model_policy(spec) if spec is not None else None,
        "arm": args.arm,
        "rust_mode": args.rust_mode,
        "hint": getattr(run_params, "hint", None),
        "hint_source": getattr(args, "hint_source", None),
        "hint_override": bool(getattr(args, "allow_nonprotocol_hint", False)),
        "evidence_reasoning": getattr(args, "evidence_reasoning", "hash"),
        "replay_mode": getattr(args, "replay_mode", "key"),
        "stage": args.stage,
        "run_params": run_params.to_dict() if run_params is not None else None,
        "budget_file": args.budget_file,
        "cache_dir": args.cache_dir,
        "replay_from": args.replay_from,
        "tasks": {
            "pattern": args.tasks,
            "selected": [str(t.relative_to(tasks_root)) for t in tasks],
        },
        "rounds": args.rounds,
        "reps": args.reps,
        "temperature": args.temperature,
        "timeout": args.timeout,
        "versions": {
            "toolchain": repo_toolchain_channel(),
            "rustc": _tool_version("rustc"),
            "cargo": _tool_version("cargo"),
            "python": sys.version.split()[0],
        },
        "baseline_tools": _baseline_tools_snapshot(args),
        "started_at": started_at,
        "ended_at": ended_at,
        "status": "running",
    }


def _write_manifest(out: Path, manifest: dict) -> None:
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2),
                                       encoding="utf-8")


class _ChatProvider:
    """Adapt an audited ``complete(system, user)`` client to the provider API.

    The system prompt is selected per request from the explicit arm x stage
    routing table; a missing route raises (never a silent fallback). A per-cell
    call budget is enforced here; transport/truncation retries and cache hits
    are recorded in ``calls``.
    """

    name = "llm"

    def __init__(self, client, *, arm: str, params) -> None:
        self.client = client
        self.arm = arm
        self.params = params
        self.cell_budget: CellBudget | None = None
        self.calls: list[dict] = []
        self._attempt = 0

    def set_cell(self, cell_id: str, task_id: str, replicate: int) -> None:
        if hasattr(self.client, "set_cell"):
            self.client.set_cell(cell_id, task_id, replicate)
        self.cell_budget = CellBudget(call_budget=self.params.call_budget,
                                      token_budget=self.params.token_budget)
        self.calls = []

    @staticmethod
    def _usage_of(outcome) -> dict:
        """Sum the normalized usage of every real attempt in this call."""
        attempts = list(getattr(outcome, "usage_attempts", []) or [])
        if attempts:
            normalized = [normalize_token_usage(u) for u in attempts]
            summed = {}
            for key in ("input", "output", "reasoning", "cached"):
                values = [n.get(key) for n in normalized if isinstance(n.get(key), int)]
                summed[key] = sum(values) if values else None
            return summed
        return normalize_token_usage(getattr(outcome, "usage", None))

    def _record(self, stage: str, system: str, user: str, outcome, error=None) -> None:
        usage = (self._usage_of(outcome) if outcome is not None
                 else {"input": None, "output": None, "reasoning": None, "cached": None})
        record = {
            "attempt": self._attempt,
            "stage": stage,
            "system_sha256": hashlib.sha256(system.encode("utf-8")).hexdigest(),
            "request_sha256": hashlib.sha256(
                (system.strip() + "\n\n" + user.strip()).encode("utf-8")).hexdigest(),
            "cache_hit": bool(getattr(outcome, "cache_hit", False)),
            "transport_attempt": getattr(outcome, "transport_attempt", 1),
            "truncation_retry": bool(getattr(outcome, "truncation_retry", False)),
            "finish_reason": getattr(outcome, "finish_reason", None),
            "finish_reasons": list(getattr(outcome, "finish_reasons", []) or []),
            "usage": usage,
            "wall_ms": getattr(outcome, "wall_ms", 0),
            "error": (str(error) if error is not None else None),
        }
        if getattr(outcome, "replay_mismatch", False):
            record["replay_mismatch"] = True
        self.calls.append(record)

    def propose(self, request):
        if self.cell_budget is not None:
            exhausted = self.cell_budget.check()
            if exhausted:
                return CandidateResponse(text="", source="llm", provider=self.name,
                                         error=exhausted)
        stage = _stage_for(self.arm, request)
        assets = prompts.route(self.arm, stage)
        if hasattr(self.client, "set_stage"):
            self.client.set_stage(stage)
        self._attempt = getattr(request, "attempt", 1)
        if hasattr(self.client, "set_attempt"):
            self.client.set_attempt(self._attempt)
        # Hash the system prompt actually sent, not a re-derived join.
        system = prompts.system_prompt_for(self.arm, stage)
        if hasattr(self.client, "set_prompt_meta"):
            self.client.set_prompt_meta(
                assets, hashlib.sha256(system.encode("utf-8")).hexdigest())
        user = _user_prompt_for(self.arm, stage, request)
        if self.cell_budget is not None:
            self.cell_budget.count_call()
        try:
            outcome = self.client.complete(system, user)
        except BudgetExceeded:
            raise
        except ModelIdentityError:
            # A model-identity mismatch invalidates the whole batch.
            raise
        except TransportError as exc:
            # A failed call can still carry usage/truncation accounting (e.g.
            # TransportTruncated): record and bill it like a real call.
            self._record(stage, system, user, exc, error=exc)
            if self.cell_budget is not None:
                self.cell_budget.add_tokens(self._usage_of(exc))
            return CandidateResponse(text="", source="llm", provider=self.name,
                                     error=str(exc))
        self._record(stage, system, user, outcome)
        if self.cell_budget is not None:
            self.cell_budget.add_tokens(self._usage_of(outcome))
        return CandidateResponse.from_usage(
            outcome.text, "llm", self.name,
            model_id=getattr(outcome, "requested_model", None),
            usage=getattr(outcome, "usage", None))


def _stage_for(arm: str, request) -> str:
    """Resolve the prompt stage for a request from the arm and its content."""
    if arm in prompts.BASELINE_ARMS:
        stage = getattr(request, "stage", None)
        allowed = {prompts.STAGE_GENERATE, prompts.STAGE_RUST_FIX,
                   prompts.STAGE_REVIEW, prompts.STAGE_TOOL_FEEDBACK}
        if stage not in allowed:
            raise KeyError(f"unknown baseline stage {stage!r} for arm {arm}")
        return stage
    if arm == "G0":
        return prompts.STAGE_GENERATE
    if request.stage == "rust":
        return prompts.STAGE_RUST
    if request.stage == "rust_fix":
        return prompts.STAGE_RUST_FIX
    if request.feedback:
        return prompts.STAGE_FEEDBACK
    return prompts.STAGE_GENERATE


def _user_prompt_for(arm: str, stage: str, request) -> str:
    if stage == prompts.STAGE_RUST_FIX:
        design = request.previous_candidate if arm in ("SKEL", "CIR") else None
        design_kind = {"SKEL": "skel", "CIR": "cir"}.get(arm)
        return prompts.rust_compile_fix_user_prompt(
            request.requirements, request.current_program or "",
            request.feedback or "", design=design, design_kind=design_kind)
    if stage == prompts.STAGE_RUST:
        if arm == "CIR":
            return prompts.rust_from_cir_user_prompt(
                request.requirements, request.previous_candidate or "",
                retry_note=request.feedback)
        return prompts.rust_from_skel_user_prompt(
            request.requirements, request.previous_candidate or "",
            retry_note=request.feedback)
    if stage == prompts.STAGE_REVIEW:
        return prompts.baseline_review_user_prompt(
            request.requirements, request.current_program or "",
            feedback=request.feedback)
    if stage == prompts.STAGE_TOOL_FEEDBACK:
        source = {"STATIC": "static", "DYNAMIC": "dynamic",
                  "DYNAMIC_M": "dynamic_monitor"}.get(arm, "static")
        return prompts.baseline_tool_feedback_user_prompt(
            request.requirements, request.current_program or "",
            request.feedback or "", source=source)
    return prompts.requirements_only_user_prompt(
        request.requirements, previous_candidate=request.previous_candidate,
        feedback=request.feedback)


def _build_provider(args: argparse.Namespace, audit: AuditLog, out: Path,
                    spec, run_params, ledger, *, client_factory=None):
    if client_factory is not None:
        inner = client_factory(spec, out)
    elif args.replay_from:
        # Replay must not load a key or open a socket. A miss raises before
        # this inner client is asked to complete.
        class _ReplayOnly:
            def complete(self, system, user):  # pragma: no cover - miss path
                raise TransportError("replay_only")
        inner = _ReplayOnly()
    else:
        # Only the real path loads .env; dry-run and injected factories do not.
        env_file = Path(args.env_file) if args.env_file else repo_root() / ".env"
        from .env import load_dotenv
        load_dotenv(env_file, override=True)
        from .channels import build_client, key_for
        from .transport import CHANNELS
        channel = CHANNELS[spec.channel]
        key = key_for(spec, dict(os.environ), channel.api_key_env)
        inner = build_client(spec, run_params, budget=ledger,
                             evidence_dir=out / "evidence", api_key=key,
                             timeout=args.timeout,
                             reasoning_log=getattr(args, "evidence_reasoning", "hash"))
    cache = ResponseCache(args.cache_dir if args.cache_dir else out / "cache")
    replay = None
    if args.replay_from:
        replay_dir = Path(args.replay_from)
        # A run directory is accepted: use its cache/ subdirectory.
        if (replay_dir / "MANIFEST.json").exists() and (replay_dir / "cache").is_dir():
            replay_dir = replay_dir / "cache"
        replay = ResponseCache(replay_dir)
    cached = CachedClient(inner, cache=cache, replay=replay,
                          model_id=spec.model_id or "", params=run_params,
                          first_round=getattr(args, "first_round", "auto"),
                          arm=args.arm,
                          replay_mode=getattr(args, "replay_mode", "key"))
    audited = _make_audited(cached, audit=audit, out=out, spec=spec, arm=args.arm)
    return _ChatProvider(audited, arm=args.arm, params=run_params)


def _make_audited(inner, *, audit, out, spec, arm):
    from .channels import AuditedClient
    return AuditedClient(inner, audit=audit, run_id=out.name, cell_id="run",
                         spec=spec, arm=arm, task_id="*", replicate=0)


class _Budget:
    def reserve(self) -> None:  # pragma: no cover - only in real runs
        return None


_CLIPPY_VERSION: str | None | bool = False
_CLIPPY_PROBE: dict | None = None
_MIRI_PRESENT: bool | None = None
_SHUTTLE_PRESENT: bool | None = None


def _toolchain_env() -> dict:
    env = dict(os.environ)
    channel = repo_toolchain_channel()
    if channel:
        env["RUSTUP_TOOLCHAIN"] = channel
    return env


def _clippy_version() -> str | None:
    """``cargo clippy --version`` on the repo toolchain, or None."""
    global _CLIPPY_VERSION
    if _CLIPPY_VERSION is not False:
        return _CLIPPY_VERSION  # type: ignore[return-value]
    try:
        proc = subprocess.run(
            ["cargo", "clippy", "--version"], capture_output=True, text=True,
            timeout=60, env=_toolchain_env())
    except (OSError, subprocess.TimeoutExpired):
        _CLIPPY_VERSION = None
        return None
    text = (proc.stdout or "").strip()
    _CLIPPY_VERSION = text if proc.returncode == 0 and text else None
    return _CLIPPY_VERSION


def _clippy_probe() -> dict | None:
    """probe_lints result, cached so a resume snapshot matches the first one."""
    global _CLIPPY_PROBE
    if _CLIPPY_PROBE is not None:
        return _CLIPPY_PROBE
    if _clippy_version() is None:
        return None
    import tempfile
    from .rusttools.clippy import probe_lints
    from .rusttools.runner import ToolRunner
    with tempfile.TemporaryDirectory(prefix="skelnet-clippy-probe-") as directory:
        found = probe_lints(ToolRunner(), directory, timeout=180.0)
    _CLIPPY_PROBE = {name: bool(ok) for name, ok in found.items()}
    return _CLIPPY_PROBE


def _miri_present() -> bool:
    global _MIRI_PRESENT
    if _MIRI_PRESENT is not None:
        return _MIRI_PRESENT
    try:
        proc = subprocess.run(
            ["cargo", "miri", "--version"], capture_output=True, text=True,
            timeout=60, env=_toolchain_env())
    except (OSError, subprocess.TimeoutExpired):
        _MIRI_PRESENT = False
        return False
    _MIRI_PRESENT = proc.returncode == 0
    return _MIRI_PRESENT


def _shuttle_prefetched() -> bool:
    """True when the cargo registry already contains shuttle 0.8.1."""
    global _SHUTTLE_PRESENT
    if _SHUTTLE_PRESENT is not None:
        return _SHUTTLE_PRESENT
    homes = [Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo"))]
    default = Path.home() / ".cargo"
    if default not in homes:
        homes.append(default)
    found = False
    for home in homes:
        if any(home.glob("registry/src/*/shuttle-0.8.1")):
            found = True
            break
    _SHUTTLE_PRESENT = found
    return found


def _missing_baseline_tools(args) -> list[str]:
    """Tools a baseline arm needs. Empty for G0/SKEL/CIR/REFINE."""
    arm = getattr(args, "arm", None)
    if arm not in prompts.BASELINE_ARMS:
        return []
    missing: list[str] = []
    if arm == "STATIC":
        if _clippy_version() is None:
            missing.append("clippy")
        from .rusttools.lockbud import locate_lockbud
        if locate_lockbud() is None:
            missing.append("lockbud")
    if arm in ("DYNAMIC", "DYNAMIC_M"):
        if not _shuttle_prefetched():
            missing.append("shuttle")
        if not _miri_present():
            missing.append("miri")
    if arm == "DYNAMIC_M":
        from .backend import find_binary
        for name, env_var in (("concir-instrument", "CONCIR_INSTRUMENT"),
                              ("concir-backend", "CONCIR_BACKEND")):
            try:
                find_binary(name, env_var=env_var)
            except FileNotFoundError:
                missing.append(name)
    return missing


def _preflight_baseline_tools(args) -> None:
    """Refuse a baseline run whose tools are missing, unless allowed."""
    from .rusttools.seeds import FEEDBACK_MIRI_SEED_COUNT
    count = getattr(args, "feedback_miri_seeds", 16)
    if not isinstance(count, int) or isinstance(count, bool) or count < 0 \
            or count > FEEDBACK_MIRI_SEED_COUNT:
        raise SystemExit(
            f"--feedback-miri-seeds must be between 0 and "
            f"{FEEDBACK_MIRI_SEED_COUNT}")
    missing = _missing_baseline_tools(args)
    if missing and not getattr(args, "allow_missing_tools", False):
        raise SystemExit(
            "missing baseline tools: " + ", ".join(missing)
            + " (install them, or pass --allow-missing-tools)")


def _baseline_tools_snapshot(args) -> dict:
    """Deterministic MANIFEST record of the feedback-tool configuration."""
    from .rusttools.lockbud import LOCKBUD_TOOLCHAIN, lockbud_commit
    from .rusttools.seeds import (FEEDBACK_MIRI_SEED_COUNT, FEEDBACK_SHUTTLE_SEED,
                                  feedback_miri_window)
    count = getattr(args, "feedback_miri_seeds", 16)
    try:
        start, used = feedback_miri_window(count)
    except ValueError:
        start, used = 0, 0
    arm = getattr(args, "arm", None)
    clippy = None
    lockbud = None
    if arm == "STATIC":
        version = _clippy_version()
        clippy = {"version": version, "lints": _clippy_probe() if version else None}
        lockbud = {"commit": lockbud_commit(),
                   "toolchain": LOCKBUD_TOOLCHAIN,
                   "present": _lockbud_present()}
    return {
        "clippy": clippy,
        "lockbud": lockbud,
        "shuttle": "0.8.1" if _shuttle_prefetched() else None,
        "seeds": {
            "shuttle": FEEDBACK_SHUTTLE_SEED,
            "miri_start": start,
            "miri_count": used,
            "miri_window": FEEDBACK_MIRI_SEED_COUNT,
        },
        "stress": {"runs": 20, "timeout_s": 10.0,
                   "shuttle_iterations": 2000, "shuttle_depth": 3},
        "first_round": getattr(args, "first_round", "auto"),
        "feedback_miri_seeds": count,
        "missing": _missing_baseline_tools(args),
    }


def _lockbud_present() -> bool:
    from .rusttools.lockbud import locate_lockbud
    return locate_lockbud() is not None


def _resolved_hint(args: argparse.Namespace) -> str:
    """Resolve ``--hint`` at call time from ``params.DEFAULT_HINT``.

    The argparse default is ``None`` so a later edit of the constant is visible
    without re-importing this module.
    """
    from . import params as params_mod
    explicit = getattr(args, "hint", None)
    if explicit:
        args.hint_source = "explicit"
        return str(explicit)
    args.hint_source = "default"
    return params_mod.DEFAULT_HINT


def _requirements_filename(hint: str) -> str:
    return "REQUIREMENTS.md" if hint == "h0" else "REQUIREMENTS.h1.md"


def _is_boundary_rel(rel: str) -> bool:
    return rel == "boundary" or rel.startswith("boundary/")


def _requirements_missing(root: Path, tasks: list[Path], hint: str) -> list[str]:
    """Non-boundary tasks that lack the requirements file for ``hint``."""
    filename = _requirements_filename(hint)
    base = root / "benchmarks" / "tasks"
    missing: list[str] = []
    for task_dir in tasks:
        rel = str(task_dir.relative_to(base))
        if _is_boundary_rel(rel):
            continue
        if not (task_dir / filename).is_file():
            missing.append(rel)
    return missing


def _preflight_hint_requirements(run_params, tasks: list[Path]) -> None:
    """Refuse a run whose selected main tasks lack the hint's requirements file."""
    missing = _requirements_missing(repo_root(), tasks, run_params.hint)
    if not missing:
        return
    filename = _requirements_filename(run_params.hint)
    raise SystemExit(
        f"missing {filename} for: " + ", ".join(missing))


def cmd_eval(args: argparse.Namespace, *, runner=None) -> int:
    from . import params as params_mod
    run_dir = Path(args.run_dir)
    manifest: dict = {}
    manifest_path = run_dir / "MANIFEST.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    hint = manifest.get("hint") or params_mod.LEGACY_HINT
    updated = 0
    for result_path in sorted(run_dir.glob("cells/**/result.json")):
        data = json.loads(result_path.read_text(encoding="utf-8"))
        workdir = result_path.parent
        rust = workdir / "candidate.rs"
        if not rust.exists():
            continue
        task = workdir.parent.relative_to(run_dir / "cells").as_posix()
        task_dir = repo_root() / "benchmarks" / "tasks" / task
        terminal = read_terminal(task_dir, hint)
        extra: dict[str, str] = {}
        trace = workdir / "cir_trace.rs"
        if trace.exists():
            extra["src/cir_trace.rs"] = trace.read_text(encoding="utf-8")
        rust_mode = data.get("rust_mode", "llm")
        oracle = RustOracle(terminal=terminal, timeout=args.timeout, runner=runner,
                            task_dir=task_dir)
        outcome = oracle.evaluate(rust.read_text(encoding="utf-8"), workdir,
                                  extra_files=extra or None,
                                  check_terminal=rust_mode != "codegen")
        data["oracle"] = oracle_result_dict(outcome)
        result_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        updated += 1
    # Keep the run's summary/report in sync with the re-evaluated cells.
    summary = _summary_from_run(run_dir)
    (run_dir / "SUMMARY.json").write_text(json.dumps(summary, indent=2),
                                          encoding="utf-8")
    (run_dir / "REPORT.md").write_text(_report_markdown([summary]), encoding="utf-8")
    print(f"re-evaluated {updated} cells")
    return 0


def _summary_from_run(run_dir: Path) -> dict:
    manifest: dict = {}
    manifest_path = run_dir / "MANIFEST.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cells = _selected_cells(run_dir, manifest)
    summary = {"run_id": manifest.get("run_id", run_dir.name),
               "arm": manifest.get("arm", "?"),
               "model": manifest.get("model", "?"),
               "cells": cells}
    if "budget" in manifest:
        summary["budget"] = manifest["budget"]
    return summary


def _selected_cells(run_dir: Path, manifest: dict) -> list[dict]:
    """Cells declared by the manifest (selected tasks x reps), else all cells.

    A run directory is single-run: stale cells from another task must not leak
    into the summary.
    """
    selected = (manifest.get("tasks") or {}).get("selected")
    reps = manifest.get("reps")
    if isinstance(selected, list) and isinstance(reps, int):
        cells = []
        for task in selected:
            for rep in range(reps):
                path = run_dir / "cells" / task / str(rep) / "result.json"
                if path.exists():
                    cells.append(json.loads(path.read_text(encoding="utf-8")))
        return cells
    return [json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(run_dir.glob("cells/**/result.json"))]


def cmd_report(args: argparse.Namespace) -> int:
    summaries = []
    for d in args.run_dirs:
        path = Path(d) / "SUMMARY.json"
        if path.exists():
            summaries.append(json.loads(path.read_text(encoding="utf-8")))
    print(_report_markdown(summaries))
    return 0


def _rate(cells: list[dict], predicate) -> str:
    if not cells:
        return "-"
    hits = sum(1 for c in cells if predicate(c))
    return f"{hits / len(cells):.0%}"


def _rate_or_dash(cells: list[dict], getter) -> str:
    """Rate over cells whose value is not None; '-' when all are None."""
    values = [getter(c) for c in cells]
    values = [v for v in values if v is not None]
    if not values:
        return "-"
    return f"{sum(1 for v in values if v) / len(values):.0%}"


def _report_markdown(summaries: list[dict]) -> str:
    lines = ["# SkelNet run report", "",
             "| run | arm | model | cells | parse rate | check pass | "
             "verify pass | mean rounds | evidence | run ok | functional |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for s in summaries:
        cells = s.get("cells", [])
        # G0 writes Rust directly: it has no check/verify/evidence/rounds stage.
        is_g0 = s.get("arm") == "G0"
        rounds = [c.get("rounds_used", 0) for c in cells if c.get("rounds_used")]
        mean_rounds = "-" if is_g0 else (
            f"{(sum(rounds) / len(rounds)):.1f}" if rounds else "-")
        verify = "-" if is_g0 else _rate(cells, lambda c: c.get("accepted"))
        evidence = "-" if is_g0 else _rate(cells, lambda c: c.get("evidence_sufficient"))
        lines.append(
            f"| {s.get('run_id', s.get('arm', '?'))} | {s.get('arm', '?')} | "
            f"{s.get('model', '?')} | {len(cells)} | "
            f"{_rate(cells, lambda c: c.get('parse_ok'))} | "
            f"{_rate(cells, lambda c: c.get('check_ok'))} | "
            f"{verify} | "
            f"{mean_rounds} | "
            f"{evidence} | "
            f"{_rate_or_dash(cells, lambda c: (c.get('oracle') or {}).get('run_ok'))} | "
            f"{_rate_or_dash(cells, lambda c: (c.get('oracle') or {}).get('functional_ok'))} |")
    return "\n".join(lines) + "\n"


def cmd_models(args: argparse.Namespace) -> int:
    from .env import load_dotenv
    from .models_probe import probe_dry_run, probe_run
    env_file = Path(args.env_file) if args.env_file else repo_root() / ".env"
    load_dotenv(env_file, override=True)
    specs = None
    if args.models:
        from .transport import resolve_model
        registry = build_registry()
        specs = [resolve_model(registry, name) for name in args.models]
    if args.dry_run:
        print(json.dumps(probe_dry_run(specs), indent=2))
        return 0
    out = Path(args.out) if args.out else Path("experiments") / f"probe-{int(time.time())}"
    document = probe_run(out, models=specs)
    print(json.dumps({"probe": str(out / 'PROBE.json'),
                      "models": len(document.get("models", []))}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skelnet")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run an arm")
    run.add_argument("--arm", default="SKEL",
                     choices=["G0", "SKEL", "CIR", "REFINE", "STATIC",
                              "DYNAMIC", "DYNAMIC_M"])
    run.add_argument("--model", default="DeepSeek Flash")
    run.add_argument("--tasks", default="all")
    run.add_argument("--reps", type=int, default=3)
    run.add_argument("--rounds", type=int, default=4)
    run.add_argument("--out", default="experiments/run")
    run.add_argument("--rust-mode", default="llm", choices=["llm", "codegen"])
    run.add_argument("--feedback-mode", default="full",
                     choices=["full", "outcome_only", "nocex", "nomap"])
    run.add_argument("--rust-when-unverified", default="last",
                     choices=["skip", "last"])
    run.add_argument("--property-ids", default="keep", choices=["keep", "opaque"])
    run.add_argument("--force", action="store_true",
                     help="overwrite a non-empty output directory")
    run.add_argument("--temperature-policy", default="provider_default",
                     choices=["provider_default", "fixed"])
    run.add_argument("--temperature", type=float, default=None)
    run.add_argument("--seed-policy", default="per_cell",
                     choices=["per_cell", "none"])
    run.add_argument("--call-budget", type=int, default=5)
    run.add_argument("--token-budget", type=int, default=200000)
    run.add_argument("--max-output-tokens", type=int, default=None)
    run.add_argument("--hint", default=None, choices=["h0", "h1"])
    run.add_argument("--stage", type=int, default=0, choices=[0, 1, 2, 3])
    run.add_argument("--budget-file",
                     default=str(repo_root() / "experiments" / "budget.json"))
    run.add_argument("--cache-dir", default=None)
    run.add_argument("--resume", action="store_true")
    run.add_argument("--replay-from", default=None)
    run.add_argument("--env-file", default=None)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--first-round", default="auto",
                     choices=["auto", "require-cache"])
    run.add_argument("--allow-missing-tools", action="store_true")
    run.add_argument("--feedback-miri-seeds", type=int, default=16)
    run.add_argument("--evidence-reasoning", default="hash", choices=["hash", "gzip"])
    run.add_argument("--replay-mode", default="key", choices=["key", "sequence"])
    run.add_argument("--allow-nonprotocol-hint", action="store_true")
    run.add_argument("--timeout", type=float, default=300.0)
    run.set_defaults(func=cmd_run)

    models = sub.add_parser("models", help="model parameter probe")
    models.add_argument("action", choices=["probe"])
    models.add_argument("--dry-run", action="store_true")
    models.add_argument("--models", nargs="*", default=None)
    models.add_argument("--out", default=None)
    models.add_argument("--env-file", default=None)
    models.set_defaults(func=cmd_models)

    ev = sub.add_parser("eval", help="re-run the oracle offline")
    ev.add_argument("run_dir")
    ev.add_argument("--timeout", type=float, default=300.0)
    ev.set_defaults(func=cmd_eval)

    from .oracle_cli import register as _register_oracle
    _register_oracle(sub)

    from .tools_cli import register as _register_tools
    _register_tools(sub)

    rep = sub.add_parser("report", help="one table over runs")
    rep.add_argument("run_dirs", nargs="+")
    rep.set_defaults(func=cmd_report)
    from .bench import register as _register_bench
    _register_bench(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
