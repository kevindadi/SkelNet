"""``python -m skelnet`` command line: run / eval / report."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from . import prompts
from .audit import AuditLog
from .backend import Backend, repo_root, sha256_file
from .oracle import RustOracle, repo_toolchain_channel
from .pipeline import (dumps, run_cir_cell, run_g0_cell, run_skel_cell)
from .providers import CandidateResponse
from .transport import build_registry, resolve_model


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


def read_terminal(task_dir: Path) -> str | None:
    """The required terminating stdout line for a task.

    Canonical source: ``requirements.json["terminal"]``. Tasks without a
    ``requirements.json`` (the boundary tasks) have no terminal line, which is
    recorded as ``terminal_check: "absent"`` and never counted as a pass.
    """
    reqs = Path(task_dir) / "requirements.json"
    if not reqs.exists():
        return None
    try:
        data = json.loads(reqs.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    terminal = data.get("terminal")
    return terminal if isinstance(terminal, str) and terminal else None


def _budget(arm: str, tasks: int, reps: int, rounds: int,
            rust_mode: str = "llm") -> dict:
    if arm == "G0":
        per_task = reps
    else:
        # Exact pipeline upper bound: up to `rounds` skeleton/CIR attempts, plus
        # one Rust call only when the Rust stage calls the LLM (not codegen).
        per_task = reps * (rounds + (1 if rust_mode == "llm" else 0))
    return {"arm": arm, "tasks": tasks, "reps": reps, "rounds": rounds,
            "rust_mode": rust_mode,
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
        return RustOracle(terminal=terminal, timeout=timeout, runner=runner)
    return factory


def cmd_run(args: argparse.Namespace, *, client_factory=None,
            oracle_factory=None, oracle_runner=None) -> int:
    if args.arm == "G0" and args.rust_mode == "codegen":
        raise SystemExit(
            "--arm G0 writes Rust directly and has no codegen stage; "
            "use --rust-mode llm")
    root = repo_root()
    tasks = _select_tasks(root, args.tasks)
    budget = _budget(args.arm, len(tasks), args.reps, args.rounds, args.rust_mode)
    if args.dry_run:
        routes = prompts.routes_for_arm(args.arm)
        print(json.dumps({
            **budget,
            "dry_run": True,
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

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    started_at = time.time()
    audit = AuditLog(out / "audit.jsonl", raw_dir=out / "raw")
    backend = Backend(timeout=args.timeout)
    manifest = _build_manifest(out, args, backend, tasks, started_at, None)
    _write_manifest(out, manifest)
    if oracle_factory is None:
        oracle_factory = default_oracle_factory(timeout=args.timeout,
                                                runner=oracle_runner)
    provider = _build_provider(args, audit, out, client_factory=client_factory)
    summary: dict = {"run_id": out.name, "arm": args.arm, "model": args.model,
                     "budget": budget, "cells": []}
    for task_dir in tasks:
        task = str(task_dir.relative_to(root / "benchmarks" / "tasks"))
        reqs = (task_dir / "requirements.json")
        requirements = reqs.read_text(encoding="utf-8") if reqs.exists() else task
        contract = task_dir / "contract.json"
        terminal = read_terminal(task_dir)
        # The factory receives the task and its terminal line, so the terminal
        # wiring is exercised (and testable) on every real run.
        task_oracle = oracle_factory(task_dir, terminal)
        for rep in range(args.reps):
            workdir = out / "cells" / task / str(rep)
            workdir.mkdir(parents=True, exist_ok=True)
            if hasattr(provider, "set_cell"):
                provider.set_cell(f"{task}/{rep}", task, rep)
            if args.arm == "G0":
                cell = run_g0_cell(task=task, requirements=requirements,
                                   provider=provider, oracle=task_oracle,
                                   workdir=workdir, replicate=rep)
            elif args.arm == "SKEL":
                cell = run_skel_cell(task=task, requirements=requirements,
                                     contract_path=contract, provider=provider,
                                     backend=backend, oracle=task_oracle,
                                     workdir=workdir, rounds=args.rounds,
                                     replicate=rep, rust_mode=args.rust_mode)
            elif args.arm == "CIR":
                cell = run_cir_cell(task=task, requirements=requirements,
                                    contract_path=contract, provider=provider,
                                    backend=backend, oracle=task_oracle,
                                    workdir=workdir, rounds=args.rounds,
                                    replicate=rep, rust_mode=args.rust_mode)
            else:
                raise SystemExit(f"unknown arm {args.arm!r}")
            (workdir / "result.json").write_text(dumps(cell), encoding="utf-8")
            if cell.rust:
                (workdir / "candidate.rs").write_text(cell.rust, encoding="utf-8")
            if cell.cir_trace:
                (workdir / "cir_trace.rs").write_text(cell.cir_trace, encoding="utf-8")
            summary["cells"].append(json.loads(dumps(cell)))
    ended_at = time.time()
    manifest["ended_at"] = ended_at
    _write_manifest(out, manifest)
    (out / "SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out / "REPORT.md").write_text(_report_markdown([summary]), encoding="utf-8")
    print(f"wrote {out}")
    return 0


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
                    ended_at: float | None) -> dict:
    spec = resolve_model(build_registry(), args.model)
    tasks_root = repo_root() / "benchmarks" / "tasks"
    return {
        "run_id": out.name,
        "git_sha": _git(["rev-parse", "HEAD"]).strip(),
        "git_dirty": bool(_git(["status", "--porcelain"]).strip()),
        "binaries": {
            "skelnet": sha256_file(backend.skelnet),
            "concir-backend": sha256_file(backend.concir),
        },
        "prompts": prompts.prompt_asset_record(),
        "model": args.model,
        "model_id": spec.model_id,
        "channel": spec.channel,
        "arm": args.arm,
        "rust_mode": args.rust_mode,
        "tasks": {
            "pattern": args.tasks,
            "selected": [str(t.relative_to(tasks_root)) for t in tasks],
        },
        "rounds": args.rounds,
        "reps": args.reps,
        # `--seed` is not applied yet: recorded as null until it takes effect.
        "seed": None,
        "seed_applied": False,
        "temperature": args.temperature,
        "timeout": args.timeout,
        "versions": {
            "toolchain": repo_toolchain_channel(),
            "rustc": _tool_version("rustc"),
            "cargo": _tool_version("cargo"),
            "python": sys.version.split()[0],
        },
        "started_at": started_at,
        "ended_at": ended_at,
    }


def _write_manifest(out: Path, manifest: dict) -> None:
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2),
                                       encoding="utf-8")


class _ChatProvider:
    """Adapt an audited ``complete(system, user)`` client to the provider API.

    The system prompt is selected per request from the explicit arm x stage
    routing table; a missing route raises (never a silent fallback).
    """

    name = "llm"

    def __init__(self, client, *, arm: str) -> None:
        self.client = client
        self.arm = arm

    def set_cell(self, cell_id: str, task_id: str, replicate: int) -> None:
        if hasattr(self.client, "set_cell"):
            self.client.set_cell(cell_id, task_id, replicate)

    def propose(self, request):
        stage = _stage_for(self.arm, request)
        assets = prompts.route(self.arm, stage)
        if hasattr(self.client, "set_stage"):
            self.client.set_stage(stage)
        if hasattr(self.client, "set_attempt"):
            self.client.set_attempt(getattr(request, "attempt", 1))
        if hasattr(self.client, "set_prompt_meta"):
            self.client.set_prompt_meta(assets, _system_sha(assets))
        system = prompts.system_prompt_for(self.arm, stage)
        user = _user_prompt_for(self.arm, stage, request)
        try:
            outcome = self.client.complete(system, user)
        except Exception as exc:  # noqa: BLE001
            return CandidateResponse(text="", source="llm", provider=self.name,
                                     error=str(exc))
        return CandidateResponse.from_usage(
            outcome.text, "llm", self.name,
            model_id=getattr(outcome, "requested_model", None),
            usage=getattr(outcome, "usage", None))


def _stage_for(arm: str, request) -> str:
    """Resolve the prompt stage for a request from the arm and its content."""
    if arm == "G0":
        return prompts.STAGE_GENERATE
    if request.stage == "rust":
        return prompts.STAGE_RUST
    if request.feedback:
        return prompts.STAGE_FEEDBACK
    return prompts.STAGE_GENERATE


def _user_prompt_for(arm: str, stage: str, request) -> str:
    if stage == prompts.STAGE_RUST:
        if arm == "CIR":
            return prompts.rust_from_cir_user_prompt(
                request.requirements, request.previous_candidate or "")
        return prompts.rust_from_skel_user_prompt(
            request.requirements, request.previous_candidate or "")
    return prompts.requirements_only_user_prompt(
        request.requirements, previous_candidate=request.previous_candidate,
        feedback=request.feedback)


def _build_provider(args: argparse.Namespace, audit: AuditLog, out: Path,
                    *, client_factory=None):
    spec = resolve_model(build_registry(), args.model)
    if client_factory is None:
        from .channels import build_client, key_for
        from .transport import CHANNELS
        channel = CHANNELS[spec.channel]
        key = key_for(spec, dict(os.environ), channel.api_key_env)
        inner = build_client(spec, budget=_Budget(), evidence_dir=out / "evidence",
                             api_key=key, temperature=args.temperature)
    else:
        inner = client_factory(spec, out)
    audited = _make_audited(inner, audit=audit, out=out, spec=spec, arm=args.arm)
    return _ChatProvider(audited, arm=args.arm)


def _make_audited(inner, *, audit, out, spec, arm):
    from .channels import AuditedClient
    return AuditedClient(inner, audit=audit, run_id=out.name, cell_id="run",
                         spec=spec, arm=arm, task_id="*", replicate=0)


class _Budget:
    def reserve(self) -> None:  # pragma: no cover - only in real runs
        return None


def cmd_eval(args: argparse.Namespace, *, runner=None) -> int:
    run_dir = Path(args.run_dir)
    updated = 0
    for result_path in sorted(run_dir.glob("cells/**/result.json")):
        data = json.loads(result_path.read_text(encoding="utf-8"))
        workdir = result_path.parent
        rust = workdir / "candidate.rs"
        if not rust.exists():
            continue
        task = workdir.parent.relative_to(run_dir / "cells").as_posix()
        terminal = read_terminal(repo_root() / "benchmarks" / "tasks" / task)
        extra: dict[str, str] = {}
        trace = workdir / "cir_trace.rs"
        if trace.exists():
            extra["src/cir_trace.rs"] = trace.read_text(encoding="utf-8")
        rust_mode = data.get("rust_mode", "llm")
        oracle = RustOracle(terminal=terminal, timeout=args.timeout, runner=runner)
        outcome = oracle.evaluate(rust.read_text(encoding="utf-8"), workdir,
                                  extra_files=extra or None,
                                  check_terminal=rust_mode != "codegen")
        data["oracle"] = {"built": outcome.built, "ran": outcome.ran,
                          "run_ok": outcome.run_ok,
                          "functional_ok": outcome.functional_ok,
                          "terminal_check": outcome.terminal_check}
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
    cells = [json.loads(path.read_text(encoding="utf-8"))
             for path in sorted(run_dir.glob("cells/**/result.json"))]
    return {"run_id": manifest.get("run_id", run_dir.name),
            "arm": manifest.get("arm", "?"),
            "model": manifest.get("model", "?"),
            "cells": cells}


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skelnet")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run an arm")
    run.add_argument("--arm", default="SKEL", choices=["G0", "SKEL", "CIR"])
    run.add_argument("--model", default="DeepSeek Flash")
    run.add_argument("--tasks", default="all")
    run.add_argument("--reps", type=int, default=3)
    run.add_argument("--rounds", type=int, default=4)
    run.add_argument("--out", default="experiments/run")
    run.add_argument("--rust-mode", default="llm", choices=["llm", "codegen"])
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--temperature", type=float, default=0.0)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--timeout", type=float, default=300.0)
    run.set_defaults(func=cmd_run)

    ev = sub.add_parser("eval", help="re-run the oracle offline")
    ev.add_argument("run_dir")
    ev.add_argument("--timeout", type=float, default=300.0)
    ev.set_defaults(func=cmd_eval)

    rep = sub.add_parser("report", help="one table over runs")
    rep.add_argument("run_dirs", nargs="+")
    rep.set_defaults(func=cmd_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
