"""``python -m skelnet`` command line: run / eval / report."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
import time
from pathlib import Path

from . import prompts
from .audit import AuditLog
from .backend import Backend, repo_root
from .oracle import RustOracle
from .pipeline import (dumps, run_cir_cell, run_g0_cell, run_skel_cell)
from .providers import CandidateProvider, CandidateResponse
from .transport import available_models, build_registry, resolve_model


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


def _budget(arm: str, tasks: int, reps: int, rounds: int) -> dict:
    if arm == "G0":
        per_task = reps
    else:
        per_task = reps * (rounds + 2)  # rounds of skeleton/CIR + 1 rust call
    return {"arm": arm, "tasks": tasks, "reps": reps, "rounds": rounds,
            "requests": tasks * per_task, "requests_per_task": per_task}


class _DryRunProvider(CandidateProvider):
    """Provider used by ``--dry-run``; never called for real."""

    name = "dry-run"

    def propose(self, request):  # pragma: no cover - never invoked
        return CandidateResponse(text="", source="dry-run", provider=self.name,
                                 error="dry run")


def cmd_run(args: argparse.Namespace) -> int:
    root = repo_root()
    tasks = _select_tasks(root, args.tasks)
    budget = _budget(args.arm, len(tasks), args.reps, args.rounds)
    if args.dry_run:
        print(json.dumps({**budget, "dry_run": True,
                          "prompts": prompts.prompt_asset_record()}, indent=2))
        return 0

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    audit = AuditLog(out / "audit.jsonl", raw_dir=out / "raw")
    oracle = RustOracle(timeout=args.timeout)
    backend = Backend(timeout=args.timeout)
    provider = _build_provider(args, audit, out)
    summary: dict = {"arm": args.arm, "model": args.model, "budget": budget,
                     "cells": []}
    for task_dir in tasks:
        task = str(task_dir.relative_to(root / "benchmarks" / "tasks"))
        reqs = (task_dir / "requirements.json")
        requirements = reqs.read_text(encoding="utf-8") if reqs.exists() else task
        contract = task_dir / "contract.json"
        for rep in range(args.reps):
            workdir = out / "cells" / task / str(rep)
            workdir.mkdir(parents=True, exist_ok=True)
            if args.arm == "G0":
                cell = run_g0_cell(task=task, requirements=requirements,
                                   provider=provider, oracle=oracle,
                                   workdir=workdir, replicate=rep)
            elif args.arm == "SKEL":
                cell = run_skel_cell(task=task, requirements=requirements,
                                     contract_path=contract, provider=provider,
                                     backend=backend, oracle=oracle,
                                     workdir=workdir, rounds=args.rounds, replicate=rep)
            elif args.arm == "CIR":
                cell = run_cir_cell(task=task, requirements=requirements,
                                    contract_path=contract, provider=provider,
                                    backend=backend, oracle=oracle,
                                    workdir=workdir, rounds=args.rounds, replicate=rep)
            else:
                raise SystemExit(f"unknown arm {args.arm!r}")
            (workdir / "result.json").write_text(dumps(cell), encoding="utf-8")
            if cell.rust:
                (workdir / "candidate.rs").write_text(cell.rust, encoding="utf-8")
            summary["cells"].append(json.loads(dumps(cell)))
    (out / "SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out / "REPORT.md").write_text(_report_markdown([summary]), encoding="utf-8")
    print(f"wrote {out}")
    return 0


class _ChatProvider:
    """Adapt an audited ``complete(system, user)`` client to the provider API."""

    name = "llm"

    def __init__(self, client, system_prompt: str, user_prompt_builder) -> None:
        self.client = client
        self.system_prompt = system_prompt
        self.user_prompt_builder = user_prompt_builder

    def propose(self, request):
        user = self.user_prompt_builder(request)
        try:
            outcome = self.client.complete(self.system_prompt, user)
        except Exception as exc:  # noqa: BLE001
            return CandidateResponse(text="", source="llm", provider=self.name,
                                     error=str(exc))
        return CandidateResponse.from_usage(
            outcome.text, "llm", self.name,
            model_id=getattr(outcome, "requested_model", None),
            usage=getattr(outcome, "usage", None))


def _build_provider(args: argparse.Namespace, audit: AuditLog, out: Path):
    spec = resolve_model(build_registry(), args.model)
    from .channels import AuditedClient, build_client, key_for
    from .transport import CHANNELS
    channel = CHANNELS[spec.channel]
    key = key_for(spec, dict(os.environ), channel.api_key_env)
    inner = build_client(spec, budget=_Budget(), evidence_dir=out / "evidence",
                         api_key=key)
    audited = AuditedClient(inner, audit=audit, run_id=out.name, cell_id="run",
                            spec=spec, arm=args.arm, task_id="*", replicate=0)
    return _ChatProvider(audited, prompts.skel_generation_system_prompt(),
                         _user_prompt_builder)


def _user_prompt_builder(request) -> str:
    if request.stage == "rust":
        from .prompts import rust_from_skel_user_prompt
        return rust_from_skel_user_prompt(request.requirements,
                                          request.previous_candidate or "")
    return prompts.requirements_only_user_prompt(
        request.requirements, previous_candidate=request.previous_candidate,
        feedback=request.feedback)


class _Budget:
    def reserve(self) -> None:  # pragma: no cover - only in real runs
        return None


def cmd_eval(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    oracle = RustOracle(timeout=args.timeout)
    updated = 0
    for result_path in run_dir.glob("cells/*/*/result.json"):
        data = json.loads(result_path.read_text(encoding="utf-8"))
        rust = result_path.parent / "candidate.rs"
        if not rust.exists():
            continue
        outcome = oracle.evaluate(rust.read_text(encoding="utf-8"), result_path.parent)
        data["oracle"] = {"built": outcome.built, "ran": outcome.ran,
                          "functional_ok": outcome.functional_ok}
        result_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        updated += 1
    print(f"re-evaluated {updated} cells")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    summaries = []
    for d in args.run_dirs:
        path = Path(d) / "SUMMARY.json"
        if path.exists():
            summaries.append(json.loads(path.read_text(encoding="utf-8")))
    print(_report_markdown(summaries))
    return 0


def _report_markdown(summaries: list[dict]) -> str:
    lines = ["# SkelNet run report", "",
             "| run | arm | model | cells | accepted | oracle functional |",
             "| --- | --- | --- | --- | --- | --- |"]
    for s in summaries:
        cells = s.get("cells", [])
        accepted = sum(1 for c in cells if c.get("accepted"))
        functional = sum(1 for c in cells
                         if (c.get("oracle") or {}).get("functional_ok"))
        lines.append(f"| {s.get('arm')} | {s.get('arm')} | {s.get('model')} | "
                     f"{len(cells)} | {accepted} | {functional} |")
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
    run.add_argument("--provider", default="real")
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
