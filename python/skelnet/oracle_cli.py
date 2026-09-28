"""``python -m skelnet oracle calibrate`` — calibrate the four-layer oracle.

Runs the oracle over reference/buggy programs (and, with ``--mutants``, the
three artificial mutant families) and writes ``CALIBRATION.json`` /
``CALIBRATION.md``. A mismatch between observed and expected outcomes exits 1
unless ``--report-only`` is given.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .oracle import RustOracle
from .rusttools.mutants import generate_mutants


def register(sub: argparse._SubParsersAction) -> None:
    oracle = sub.add_parser("oracle", help="independent four-layer oracle")
    actions = oracle.add_subparsers(dest="oracle_action", required=True)
    cal = actions.add_parser("calibrate", help="calibrate over fixtures/tasks")
    cal.add_argument("--tasks", default="all")
    cal.add_argument("--fixtures", default=None)
    cal.add_argument("--out", required=True)
    cal.add_argument("--mutants", action="store_true")
    cal.add_argument("--layers", default="O1,O2,O3,O4")
    cal.add_argument("--report-only", action="store_true")
    cal.add_argument("--timeout", type=float, default=300.0)
    cal.set_defaults(func=cmd_calibrate)


def _parse_layers(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in text.split(",") if part.strip())


def _safe(name: str) -> str:
    """A filesystem-safe component (macOS miri rejects `:` in a path)."""
    return name.replace("/", "__").replace(":", "-")


def _task_dirs(args) -> list[Path]:
    from . import cli
    if args.fixtures:
        base = Path(args.fixtures)
        return sorted(p for p in base.iterdir() if p.is_dir())
    root = cli.repo_root()
    return cli._select_tasks(root, args.tasks)


def _programs(task_dir: Path, *, with_mutants: bool) -> list[dict]:
    """Every program to evaluate for a task, with its expectation."""
    rust_dir = task_dir / "rust"
    expect_path = rust_dir / "expect.json"
    expectations: dict = {}
    if expect_path.exists():
        expectations = json.loads(expect_path.read_text(encoding="utf-8"))
    out: list[dict] = []

    def add(name: str, source: str, default_functional: bool):
        expect = expectations.get(name, {"functional": default_functional})
        if not isinstance(expect, dict):
            expect = {"functional": default_functional}
        expect.setdefault("functional", default_functional)
        out.append({"name": name, "source": source, "expect": expect})

    if (rust_dir / "fixed.rs").exists():
        add("fixed.rs", (rust_dir / "fixed.rs").read_text(encoding="utf-8"), True)
    for buggy in sorted(rust_dir.glob("buggy*.rs")):
        add(buggy.name, buggy.read_text(encoding="utf-8"), False)
    if with_mutants and (rust_dir / "fixed.rs").exists():
        from . import cli
        terminal = cli.read_terminal(task_dir)
        fixed = (rust_dir / "fixed.rs").read_text(encoding="utf-8")
        for name, spec in generate_mutants(fixed, terminal=terminal).items():
            if spec["source"] is None:
                out.append({"name": f"mutant:{name}", "source": None,
                            "expect": {"functional": False},
                            "unsupported": spec["reason"]})
            else:
                out.append({"name": f"mutant:{name}", "source": spec["source"],
                            "expect": {"functional": False}})
    return out


def _matches(result, expect: dict) -> bool:
    if result.functional_ok != expect.get("functional"):
        return False
    if "layer" in expect:
        layer = result.layers.get(expect["layer"])
        if layer is None or layer.status != "fail":
            return False
        if expect.get("category") and layer.category != expect["category"]:
            return False
    return True


def cmd_calibrate(args: argparse.Namespace, *, runner=None) -> int:
    from . import cli
    layers = _parse_layers(args.layers)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks = _task_dirs(args)

    report_tasks: list[dict] = []
    shuttle_unsupported: list[str] = []
    o4_coverage: list[dict] = []
    design_loss: list[str] = []
    mismatches = 0
    total = 0

    for task_dir in tasks:
        task = task_dir.name if args.fixtures else str(
            task_dir.relative_to(cli.repo_root() / "benchmarks" / "tasks"))
        terminal = cli.read_terminal(task_dir)
        programs_report: list[dict] = []
        for program in _programs(task_dir, with_mutants=args.mutants):
            total += 1
            label = f"{task}/{program['name']}"
            if program["source"] is None:
                programs_report.append({
                    "program": program["name"], "unsupported": program.get("unsupported"),
                    "matched": False})
                mismatches += 1
                continue
            workdir = out_dir / _safe(task) / _safe(program["name"])
            oracle = RustOracle(terminal=terminal, timeout=args.timeout,
                                task_dir=task_dir, layers=layers, runner=runner)
            result = oracle.evaluate(program["source"], workdir)
            matched = _matches(result, program["expect"])
            if not matched:
                mismatches += 1
            entry = {
                "program": program["name"],
                "expect": program["expect"],
                "functional_ok": result.functional_ok,
                "functional_ok_no_o4": result.functional_ok_no_o4,
                "terminal_check": result.terminal_check,
                "oracle_complete": result.oracle_complete,
                "layers": {name: layer.to_dict() for name, layer in result.layers.items()},
                "wall_ms": {name: (layer.wall_ms or 0)
                            for name, layer in result.layers.items()},
                "matched": matched,
            }
            programs_report.append(entry)
            for name, layer in result.layers.items():
                if layer.category == "shuttle_unsupported":
                    shuttle_unsupported.append(f"{label}:O3")
            o4 = result.layers.get("O4")
            if o4 is not None and o4.detail and "coverage" in (o4.detail or ""):
                o4_coverage.append({"program": label, "detail": o4.detail})
            if o4 is not None and o4.category == "design_loss":
                design_loss.append(label)
        report_tasks.append({"task": task, "programs": programs_report})

    document = {
        "schema_version": "skelnet-calibration-v1",
        "created_at": time.time(),
        "layers": list(layers),
        "summary": {"total": total, "matched": total - mismatches,
                    "mismatched": mismatches},
        "tasks": report_tasks,
        "shuttle_unsupported": shuttle_unsupported,
        "o4_coverage": o4_coverage,
        "design_loss": design_loss,
    }
    (out_dir / "CALIBRATION.json").write_text(json.dumps(document, indent=2),
                                              encoding="utf-8")
    (out_dir / "CALIBRATION.md").write_text(_markdown(document), encoding="utf-8")
    print(json.dumps(document["summary"], indent=2))
    if mismatches and not args.report_only:
        return 1
    return 0


def _markdown(document: dict) -> str:
    lines = ["# Oracle calibration", "",
             f"- total: {document['summary']['total']}",
             f"- matched: {document['summary']['matched']}",
             f"- mismatched: {document['summary']['mismatched']}", "",
             "| task | program | functional_ok | O1 | O2 | O3 | O4 | matched |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for task in document["tasks"]:
        for program in task["programs"]:
            if program.get("unsupported"):
                lines.append(f"| {task['task']} | {program['program']} | - | - | - | - | - | no |")
                continue
            layers = program["layers"]
            cells = [layers.get(name, {}).get("status", "-")
                     for name in ("O1", "O2", "O3", "O4")]
            lines.append(
                f"| {task['task']} | {program['program']} | {program['functional_ok']} "
                f"| {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} "
                f"| {'yes' if program['matched'] else 'no'} |")
    if document["shuttle_unsupported"]:
        lines += ["", "## shuttle_unsupported", ""]
        lines += [f"- {item}" for item in document["shuttle_unsupported"]]
    if document["design_loss"]:
        lines += ["", "## design_loss", ""]
        lines += [f"- {item}" for item in document["design_loss"]]
    if document["o4_coverage"]:
        lines += ["", "## O4 coverage", ""]
        lines += [f"- {item['program']}: {item['detail']}"
                  for item in document["o4_coverage"]]
    return "\n".join(lines) + "\n"
