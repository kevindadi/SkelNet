"""``python -m skelnet tools`` — baseline-tool utilities (round 4).

``fp-check`` runs the STATIC tools (clippy concurrency lints and lockbud) on
every task's ``rust/fixed.rs`` and ``rust/buggy*.rs`` and writes a false-positive
/ detection report. A missing tool is recorded as ``unavailable``; the command
still exits 0.
"""

from __future__ import annotations

import json
from pathlib import Path

from .backend import repo_root
from .rusttools.clippy import CONCURRENCY_LINTS, run_clippy
from .rusttools.lockbud import run_lockbud
from .rusttools.runner import ToolRunner


def register(sub) -> None:
    tools = sub.add_parser("tools", help="baseline tool utilities")
    inner = tools.add_subparsers(dest="tools_cmd", required=True)
    fp = inner.add_parser("fp-check", help="false-positive check on fixed/buggy Rust")
    fp.add_argument("--tasks", default="all")
    fp.add_argument("--out", required=True)
    fp.add_argument("--timeout", type=float, default=300.0)
    fp.set_defaults(func=cmd_fp_check)


def _programs(task_dir: Path) -> list[tuple[str, Path]]:
    rust = task_dir / "rust"
    if not rust.is_dir():
        return []
    found: list[tuple[str, Path]] = []
    fixed = rust / "fixed.rs"
    if fixed.is_file():
        found.append(("fixed", fixed))
    for path in sorted(rust.glob("buggy*.rs")):
        found.append(("buggy", path))
    return found


def _clippy_column(result) -> dict:
    if result.unavailable:
        return {"status": "unavailable", "findings": []}
    return {"status": "ok", "findings": [d.to_dict() for d in result.clippy]}


def _lockbud_column(result) -> dict:
    if result.unavailable:
        return {"status": "unavailable", "records": []}
    return {"status": "ok", "records": [h.to_dict() for h in result.hits]}


def _rate(hits: int, total: int) -> float | None:
    if total == 0:
        return None
    return hits / total


def cmd_fp_check(args) -> int:
    from .cli import _select_tasks
    root = repo_root()
    tasks = _select_tasks(root, args.tasks)
    tools = ToolRunner()
    rows = []
    counts = {
        "clippy": {"fixed_hits": 0, "fixed_n": 0, "buggy_hits": 0, "buggy_n": 0},
        "lockbud": {"fixed_hits": 0, "fixed_n": 0, "buggy_hits": 0, "buggy_n": 0},
    }
    for task_dir in tasks:
        rel = str(task_dir.relative_to(root / "benchmarks" / "tasks"))
        programs = []
        for role, path in _programs(task_dir):
            source = path.read_text(encoding="utf-8")
            probe = Path(args.out) / "work" / rel / path.stem
            clippy = run_clippy(tools, probe / "clippy", source,
                                lints=CONCURRENCY_LINTS, timeout=args.timeout)
            lockbud = run_lockbud(tools, probe / "lockbud", source,
                                  timeout=args.timeout)
            clippy_col = _clippy_column(clippy)
            lockbud_col = _lockbud_column(lockbud)
            programs.append({
                "path": str(path.relative_to(task_dir)),
                "role": role,
                "clippy": clippy_col,
                "lockbud": lockbud_col,
            })
            for name, col in (("clippy", clippy_col), ("lockbud", lockbud_col)):
                if col["status"] != "ok":
                    continue
                key = "findings" if name == "clippy" else "records"
                hit = bool(col[key])
                bucket = "fixed" if role == "fixed" else "buggy"
                counts[name][f"{bucket}_n"] += 1
                if hit:
                    counts[name][f"{bucket}_hits"] += 1
        rows.append({"task": rel, "programs": programs})

    summary = {}
    for name, c in counts.items():
        summary[name] = {
            "fixed_fp_rate": _rate(c["fixed_hits"], c["fixed_n"]),
            "buggy_detection_rate": _rate(c["buggy_hits"], c["buggy_n"]),
            "fixed_hits": c["fixed_hits"],
            "fixed_n": c["fixed_n"],
            "buggy_hits": c["buggy_hits"],
            "buggy_n": c["buggy_n"],
        }
    document = {"lints": list(CONCURRENCY_LINTS), "tasks": rows, "summary": summary}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "FP_CHECK.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "FP_CHECK.md").write_text(_markdown(document), encoding="utf-8")
    print(f"wrote {out / 'FP_CHECK.md'}")
    return 0


def _fmt_rate(value) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"


def _markdown(document: dict) -> str:
    lines = ["# Lockbud / clippy false-positive check", ""]
    lines.append("| tool | fixed.rs false-positive rate | buggy*.rs detection rate |")
    lines.append("| --- | --- | --- |")
    for name, summary in document["summary"].items():
        lines.append(
            f"| {name} | {_fmt_rate(summary['fixed_fp_rate'])} "
            f"({summary['fixed_hits']}/{summary['fixed_n']}) | "
            f"{_fmt_rate(summary['buggy_detection_rate'])} "
            f"({summary['buggy_hits']}/{summary['buggy_n']}) |")
    lines.append("")
    for task in document["tasks"]:
        lines.append(f"## {task['task']}")
        lines.append("")
        for program in task["programs"]:
            lines.append(f"### {program['path']} ({program['role']})")
            lines.append("")
            lines.append(f"- clippy: {program['clippy']['status']}")
            for finding in program["clippy"]["findings"]:
                lines.append(f"  - `{finding.get('code')}` {finding.get('message')}")
            lines.append(f"- lockbud: {program['lockbud']['status']}")
            for record in program["lockbud"]["records"]:
                lines.append(f"  - `{record.get('bug_kind')}`")
            lines.append("")
    return "\n".join(lines)
