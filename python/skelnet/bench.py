"""Benchmark completeness checks and difficulty tiers.

``bench validate`` reports V1–V9 for each task. ``bench tiers`` computes a
tier from the gold ConcIR program and the explored state count. Neither
command writes under ``benchmarks/`` unless ``tiers --write`` is passed, and
this round does not commit that output.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from .backend import Backend, repo_root, sha256_file

CHECKS = ("V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9")
SYNC_TYPES = ("Mutex", "Condvar", "Semaphore", "Channel", "Atomic")
_PRINT_MACROS = ("println", "print", "writeln", "write")
_REF_FIELDS = ("resource", "condvar", "lock", "channel", "mutex", "semaphore")
_LAYER_CATEGORIES = {
    "O1": {"no_build", "policy_violation"},
    "O2": {"hang", "crash", "wrong_output", "no_output"},
    "O3": {"deadlock", "panic", "thread_leak", "ub"},
    "O4": {"monitor_fail", "not_observed", "unmapped", "design_loss"},
}
_TIERS = ("L1", "L2", "L3")


class ToolUnavailable(str):
    """Binary is missing. Only this type is a skip; any other error is a fail."""
_MAIN_FILES = (
    "spec.md", "requirements.json", "REQUIREMENTS.md", "REQUIREMENTS.h1.md",
    "contract.json", "gold.skel", "gold.cir.json", "ground_truth.json",
    "rust/fixed.rs", "rust/expect.json",
)
_BOUNDARY_FILES = ("contract.json", "ground_truth.json", "spec.md")
_HINT_FILES = {"h0": "REQUIREMENTS.md", "h1": "REQUIREMENTS.h1.md"}
_R_NUM = re.compile(r"\bR(\d+)\.")


def register(sub) -> None:
    """Register ``bench validate`` and ``bench tiers`` on the root parser."""
    bench = sub.add_parser("bench", help="benchmark completeness and tiers")
    commands = bench.add_subparsers(dest="bench_command", required=True)

    validate = commands.add_parser("validate", help="check task files")
    _common(validate)
    validate.add_argument("--checks", default=None,
                          help="comma-separated subset of V1..V9")
    validate.add_argument("--run", action="store_true",
                          help="also build and run rust/fixed.rs (V7)")
    validate.add_argument("--oracle", action="store_true",
                          help="also score fixed/buggy programs (V8)")
    validate.add_argument("--strict", action="store_true",
                          help="V2 also requires tier L1/L2/L3")
    validate.set_defaults(func=cmd_validate)

    tiers = commands.add_parser("tiers", help="compute difficulty tiers")
    _common(tiers)
    tiers.add_argument("--write", action="store_true",
                       help="write benchmarks/TIERS.md and requirements.json keys")
    tiers.set_defaults(func=cmd_tiers)


def _common(parser) -> None:
    parser.add_argument("--tasks", default="all")
    parser.add_argument("--root", default=None)
    parser.add_argument("--json", action="store_true")


def cmd_validate(args) -> int:
    root = Path(args.root) if args.root else repo_root()
    tasks, unmatched = _select_patterns(root, args.tasks)
    if unmatched or not tasks:
        _report_unmatched(unmatched, args.tasks)
        return 2
    checks = _parse_checks(args.checks)
    report = validate_repo(
        root, args.tasks, checks=checks, run=bool(args.run),
        oracle=bool(args.oracle), strict=bool(args.strict), tasks=tasks)
    _emit(report, json_out=bool(args.json), kind="validate")
    return 1 if any(c["status"] == "fail" for task in report["tasks"] for c in task["checks"]) else 0


def cmd_tiers(args) -> int:
    root = Path(args.root) if args.root else repo_root()
    tasks, unmatched = _select_patterns(root, args.tasks)
    if unmatched or not tasks:
        _report_unmatched(unmatched, args.tasks)
        return 2
    base = root / "benchmarks" / "tasks"
    main_tasks = [task for task in tasks
                  if not _is_boundary(str(task.relative_to(base)))]
    if not main_tasks:
        print("no main tasks to tier (boundary tasks are not tiered)", file=sys.stderr)
        return 2
    report = tier_repo(root, args.tasks, write=bool(args.write), tasks=main_tasks)
    _emit(report, json_out=bool(args.json), kind="tiers")
    return 0


def _report_unmatched(unmatched: list[str], pattern: str) -> None:
    names = unmatched or [str(pattern)]
    print("unmatched task patterns: " + ", ".join(names), file=sys.stderr)


def _select_patterns(root: Path, pattern: str | None) -> tuple[list[Path], list[str]]:
    """Comma-separated patterns. ``all`` is unchanged.

    Returns selected task directories in directory order, and the patterns
    that matched nothing. An empty repository makes ``all`` unmatched.
    """
    from . import cli
    text = "all" if pattern in (None, "") else str(pattern)
    universe = cli._select_tasks(root, "all")
    if text == "all":
        return (universe, []) if universe else ([], ["all"])
    parts = [part.strip() for part in text.split(",") if part.strip()]
    if not parts:
        return [], [text]
    order = {task: index for index, task in enumerate(universe)}
    chosen: dict[Path, int] = {}
    unmatched: list[str] = []
    for part in parts:
        hits = cli._select_tasks(root, part)
        if not hits:
            unmatched.append(part)
            continue
        for task in hits:
            chosen.setdefault(task, order.get(task, 10**9))
    ordered = [task for task, _index in sorted(chosen.items(), key=lambda item: item[1])]
    return ordered, unmatched


def _parse_checks(text: str | None) -> tuple[str, ...]:
    if not text:
        return CHECKS
    chosen = tuple(part.strip().upper() for part in text.split(",") if part.strip())
    unknown = [name for name in chosen if name not in CHECKS]
    if unknown or not chosen:
        raise SystemExit(f"unknown checks: {', '.join(unknown) or '(empty)'}")
    return chosen


def _emit(report: dict, *, json_out: bool, kind: str) -> None:
    if json_out:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    if kind == "validate":
        print(_validate_markdown(report))
    else:
        print(_tiers_markdown(report))


def validate_repo(root: Path | str, pattern: str = "all", *,
                  checks: tuple[str, ...] = CHECKS, run: bool = False,
                  oracle: bool = False, strict: bool = False,
                  tools=None, oracle_factory: Callable | None = None,
                  tasks: list[Path] | None = None) -> dict:
    """Run the selected checks. ``tools`` and ``oracle_factory`` are test hooks."""
    root = Path(root)
    if tasks is None:
        tasks, _unmatched = _select_patterns(root, pattern)
    tools = tools if tools is not None else RealTools()
    rows = []
    for task_dir in tasks:
        rel = str(task_dir.relative_to(root / "benchmarks" / "tasks"))
        row_checks = []
        for name in checks:
            if name == "V7" and not run:
                row_checks.append(_row("V7", "skip", "not requested (--run)"))
                continue
            if name == "V8" and not oracle:
                row_checks.append(_row("V8", "skip", "not requested (--oracle)"))
                continue
            if name in ("V2", "V3", "V6") and _is_boundary(rel):
                row_checks.append(_row(name, "skip", "boundary task has no h1 requirements or reference program"))
                continue
            row_checks.append(_run_check(
                name, root, task_dir, rel, strict=strict, tools=tools,
                oracle_factory=oracle_factory))
        rows.append({"task": rel, "checks": row_checks})
    failed = sum(1 for task in rows for check in task["checks"] if check["status"] == "fail")
    return {"tasks": rows, "fail_count": failed}


def _run_check(name, root, task_dir, rel, *, strict, tools, oracle_factory) -> dict:
    try:
        return _dispatch_check(
            name, root, task_dir, rel, strict=strict, tools=tools,
            oracle_factory=oracle_factory)
    except Exception as exc:
        return _row(name, "fail", f"{type(exc).__name__}: {exc}")


def _dispatch_check(name, root, task_dir, rel, *, strict, tools, oracle_factory) -> dict:
    fn = {
        "V1": _v1, "V2": _v2, "V3": _v3, "V4": _v4, "V5": _v5,
        "V6": _v6, "V7": _v7, "V8": _v8, "V9": _v9,
    }[name]
    if name == "V2":
        return fn(task_dir, strict=strict)
    if name in ("V4", "V5"):
        return fn(root, task_dir, rel, tools=tools)
    if name == "V8":
        return fn(root, task_dir, rel, oracle_factory=oracle_factory)
    if name == "V9":
        return fn(root, task_dir, rel)
    if name == "V6":
        return fn(root, task_dir, rel)
    return fn(task_dir, rel) if name in ("V3", "V7") else fn(task_dir)


def _as_tool_row(name: str, payload, error) -> dict | None:
    """Turn a tool error into a check row. Unavailable skips; anything else fails."""
    if error is None or payload is not None:
        return None
    if isinstance(error, ToolUnavailable):
        return _row(name, "skip", str(error))
    return _row(name, "fail", str(error))


def _row(name: str, status: str, reason: str) -> dict:
    return {"id": name, "status": status, "reason": reason}


def _is_boundary(rel: str) -> bool:
    return rel == "boundary" or rel.startswith("boundary/")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _v1(task_dir: Path) -> dict:
    boundary = task_dir.parent.name == "boundary"
    missing = []
    if boundary:
        for name in _BOUNDARY_FILES:
            if not (task_dir / name).is_file():
                missing.append(name)
    else:
        for name in _MAIN_FILES:
            if not (task_dir / name).is_file():
                missing.append(name)
        buggy = list((task_dir / "rust").glob("buggy*.rs")) if (task_dir / "rust").is_dir() else []
        if not buggy:
            missing.append("rust/buggy*.rs")
    if missing:
        return _row("V1", "fail", "missing " + ", ".join(missing))
    return _row("V1", "pass", "required files are present")


def _v2(task_dir: Path, *, strict: bool = False) -> dict:
    path = task_dir / "requirements.json"
    if not path.is_file():
        return _row("V2", "fail", "requirements.json is missing")
    try:
        data = _read_json(path)
    except json.JSONDecodeError as exc:
        return _row("V2", "fail", f"requirements.json is not JSON: {exc}")
    if not isinstance(data, dict):
        return _row("V2", "fail", "requirements.json must be an object")
    terminal = data.get("terminal")
    if not isinstance(terminal, str) or not terminal:
        return _row("V2", "fail", "terminal must be a non-empty string")
    entities = data.get("entities")
    if not isinstance(entities, dict):
        return _row("V2", "fail", "entities.roles and entities.resources are missing")
    roles = entities.get("roles")
    resources = entities.get("resources")
    if not isinstance(roles, list):
        return _row("V2", "fail", "entities.roles must be a list")
    if not isinstance(resources, list):
        return _row("V2", "fail", "entities.resources must be a list")
    if terminal == "DONE done=1":
        other = data.get("terminal_v2")
        if not isinstance(other, str) or not other:
            return _row("V2", "fail", "terminal DONE done=1 requires terminal_v2")
        if other == terminal:
            return _row("V2", "fail", "terminal_v2 must differ from terminal")
    params = data.get("protocol_params", None)
    if "protocol_params" in data:
        params_error = _protocol_params_error(params)
        if params_error:
            return _row("V2", "fail", params_error)
    hints = data.get("hint_variants")
    if hints is not None:
        if not isinstance(hints, (dict, list)):
            return _row("V2", "fail", "hint_variants must be a list or object")
        names = list(hints)
        for hint in names:
            filename = _HINT_FILES.get(str(hint))
            if filename is None:
                return _row("V2", "fail", f"hint_variants has unknown hint {hint}")
            if not (task_dir / filename).is_file():
                return _row("V2", "fail", f"hint {hint} has no {filename}")
    if strict:
        tier = data.get("tier")
        if tier not in ("L1", "L2", "L3"):
            return _row("V2", "fail", "strict mode requires tier L1, L2, or L3")
    return _row("V2", "pass", "requirements.json fields are present")


def _v3(task_dir: Path, rel: str) -> dict:
    from . import cli
    h0 = task_dir / "REQUIREMENTS.md"
    h1 = task_dir / "REQUIREMENTS.h1.md"
    if not h0.is_file() or not h1.is_file():
        return _row("V3", "fail", "REQUIREMENTS.md and REQUIREMENTS.h1.md are both required")
    text0 = h0.read_text(encoding="utf-8")
    text1 = h1.read_text(encoding="utf-8")
    nums0 = set(_R_NUM.findall(text0))
    nums1 = set(_R_NUM.findall(text1))
    if nums0 != nums1:
        return _row("V3", "fail", f"R-number sets differ: h0={sorted(nums0)} h1={sorted(nums1)}")
    ent0 = _entities_section(text0)
    ent1 = _entities_section(text1)
    if ent0 is None or ent1 is None:
        return _row("V3", "fail", "both files need an Entities section")
    if ent0 != ent1:
        return _row("V3", "fail", "Entities sections differ")
    if "[U]" in text1:
        return _row("V3", "fail", "REQUIREMENTS.h1.md contains [U]")
    terminal = cli.read_terminal(task_dir)
    if not terminal or f"`{terminal}`" not in text1:
        return _row("V3", "fail", "REQUIREMENTS.h1.md does not quote the expected terminal line")
    for forbidden in ("clauses", "contract.json", rel):
        if forbidden in text1:
            return _row("V3", "fail", f"REQUIREMENTS.h1.md contains {forbidden}")
    return _row("V3", "pass", "h1 matches h0 and quotes the terminal line")


def _entities_section(text: str) -> str | None:
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == "## Entities":
            start = index
            break
    if start is None:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return "\n".join(lines[start:end]).rstrip("\n")


def _v4(root: Path, task_dir: Path, rel: str, *, tools) -> dict:
    devs = _deviations(root)
    if _unmigrated_deviation(devs, rel):
        return _row("V4", "skip", "baseline_deviation without moved_to")
    entry = _baseline_entry(root, rel, devs)
    if _is_boundary(rel):
        return _v4_boundary(task_dir, entry, tools)
    if entry is None:
        return _row("V4", "fail", "no BASELINE entry")
    skel = task_dir / "gold.skel"
    contract = task_dir / "contract.json"
    if not skel.is_file() or not contract.is_file():
        return _row("V4", "fail", "gold.skel and contract.json are required")
    payload, error = tools.verify_skel(skel, contract)
    row = _as_tool_row("V4", payload, error)
    if row is not None:
        return row
    return _compare_baseline("V4", entry, payload)


def _v4_boundary(task_dir: Path, entry: dict | None, tools) -> dict:
    reasons = []
    cir = task_dir / "gold.cir.json"
    direct = task_dir / "direct.skel"
    if not cir.is_file() and not direct.is_file():
        return _row("V4", "skip", "boundary task has no gold.cir.json or direct.skel")
    if cir.is_file():
        if entry is None:
            return _row("V4", "fail", "no BASELINE entry for gold.cir.json")
        contract = task_dir / "contract.json"
        payload, error = tools.explore(cir, contract if contract.is_file() else None)
        row = _as_tool_row("V4", payload, error)
        if row is not None:
            return row
        compared = _compare_baseline("V4", entry, payload)
        if compared["status"] != "pass":
            return compared
        reasons.append("gold.cir.json matches BASELINE")
    if direct.is_file():
        code, codes, error = tools.check_skel(direct)
        if error:
            if isinstance(error, ToolUnavailable):
                return _row("V4", "skip", str(error))
            return _row("V4", "fail", str(error))
        if code != 1:
            return _row("V4", "fail", f"direct.skel check exited {code}, expected 1")
        shown = ", ".join(codes) if codes else "(no code)"
        reasons.append(f"direct.skel rejected ({shown})")
    return _row("V4", "pass", "; ".join(reasons) or "boundary gold checked")


def _compare_baseline(name: str, entry: dict, payload: dict) -> dict:
    if str(payload.get("outcome")) != str(entry.get("outcome")):
        return _row(name, "fail",
                    f"outcome {payload.get('outcome')} != baseline {entry.get('outcome')}")
    if bool(payload.get("complete")) != bool(entry.get("complete")):
        return _row(name, "fail",
                    f"complete {payload.get('complete')} != baseline {entry.get('complete')}")
    got = {str(item.get("id")): str(item.get("outcome"))
           for item in (payload.get("properties") or []) if isinstance(item, dict)}
    want = {str(item.get("id")): str(item.get("outcome"))
            for item in (entry.get("properties") or []) if isinstance(item, dict)}
    if got != want:
        missing = sorted(set(want) - set(got))
        extra = sorted(set(got) - set(want))
        differ = sorted(key for key in set(got) & set(want) if got[key] != want[key])
        return _row(name, "fail",
                    f"properties differ missing={missing} extra={extra} changed={differ}")
    return _row(name, "pass", "outcome, complete, and properties match BASELINE")


def _v5(root: Path, task_dir: Path, rel: str, *, tools) -> dict:
    ext = _load_tasks(root / "benchmarks" / "BASELINE_EXT.json")
    if rel not in ext:
        return _row("V5", "skip", "task is not in BASELINE_EXT.json")
    skel = task_dir / "gold.skel"
    cir = task_dir / "gold.cir.json"
    if not skel.is_file() or not cir.is_file():
        return _row("V5", "fail", "gold.skel and gold.cir.json are required")
    lowered, error = tools.lower_json(skel)
    row = _as_tool_row("V5", lowered, error)
    if row is not None:
        return row
    try:
        committed = _read_json(cir)
    except json.JSONDecodeError as exc:
        return _row("V5", "fail", f"gold.cir.json is not JSON: {exc}")
    if _canon(lowered) != _canon(committed):
        return _row("V5", "fail", "lowered gold.skel does not match gold.cir.json")
    return _row("V5", "pass", "lowered JSON matches gold.cir.json")


def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _v6(root: Path, task_dir: Path, rel: str) -> dict:
    from . import cli
    allow = _allowlist(root).get(rel)
    if isinstance(allow, str):
        return _row("V6", "skip", f"terminal_allowlist: {allow}")
    fixed = task_dir / "rust" / "fixed.rs"
    if not fixed.is_file():
        return _row("V6", "fail", "rust/fixed.rs is missing")
    terminal = cli.read_terminal(task_dir)
    if not terminal:
        return _row("V6", "fail", "task has no terminal line")
    source = fixed.read_text(encoding="utf-8")
    if any(line.strip() == terminal for line in _literal_lines(source)):
        return _row("V6", "fail", "expected terminal line appears as a string literal")
    formats = _print_formats(source)
    if not any(_format_matches_terminal(fmt, terminal) for fmt in formats):
        return _row("V6", "fail", "no print macro formats the whole terminal line")
    return _row("V6", "pass", "a print macro formats the terminal line")


def _v7(task_dir: Path, rel: str) -> dict:
    from . import cli
    from .oracle import CONCIR_SYNC_CRATE, cargo_toml, repo_toolchain_channel
    from .rusttools.stress import last_nonempty_line
    fixed = task_dir / "rust" / "fixed.rs"
    if not fixed.is_file():
        return _row("V7", "fail", "rust/fixed.rs is missing")
    terminal = cli.read_terminal(task_dir)
    if not terminal:
        return _row("V7", "fail", "task has no terminal line")
    if not _cargo_available():
        return _row("V7", "skip", "cargo is not available")
    source = fixed.read_text(encoding="utf-8")
    try:
        with tempfile.TemporaryDirectory(prefix="skelnet-bench-") as tmp:
            project = Path(tmp)
            (project / "src").mkdir()
            (project / "Cargo.toml").write_text(cargo_toml("bench_fixed"), encoding="utf-8")
            (project / "src" / "main.rs").write_text(source, encoding="utf-8")
            env = os.environ.copy()
            env.pop("RUSTC_WRAPPER", None)
            env.pop("LOCKBUD_FLAGS", None)
            env.pop("LOCKBUD_LOG", None)
            channel = repo_toolchain_channel()
            if channel:
                env["RUSTUP_TOOLCHAIN"] = channel
            build = subprocess.run(
                ["cargo", "build", "--offline", "--quiet"], cwd=project, env=env,
                capture_output=True, text=True, timeout=180)
            if build.returncode != 0:
                detail = (build.stderr or build.stdout or "cargo build failed").strip()
                return _row("V7", "fail", detail[-400:])
            binary = project / "target" / "debug" / "bench_fixed"
            run = subprocess.run(
                [str(binary)], cwd=project, env=env, capture_output=True, text=True,
                timeout=10)
    except subprocess.TimeoutExpired:
        return _row("V7", "fail", "timed out")
    except OSError as exc:
        return _row("V7", "fail", str(exc))
    if "panicked" in (run.stderr or ""):
        return _row("V7", "fail", "panicked")
    if run.returncode != 0:
        return _row("V7", "fail", f"exit {run.returncode}")
    last = last_nonempty_line(run.stdout or "")
    if last != terminal:
        return _row("V7", "fail", f"last line {last!r} != {terminal!r}")
    # Touch the crate path so a missing runtime is obvious in the reason above.
    if not CONCIR_SYNC_CRATE.is_dir():
        return _row("V7", "fail", "runtime/concir_sync is missing")
    return _row("V7", "pass", "fixed.rs prints the terminal line")


def _v8(root: Path, task_dir: Path, rel: str, *, oracle_factory=None) -> dict:
    from . import cli
    fixed = task_dir / "rust" / "fixed.rs"
    if not fixed.is_file():
        return _row("V8", "fail", "rust/fixed.rs is missing")
    buggy = sorted((task_dir / "rust").glob("buggy*.rs"))
    if not buggy:
        return _row("V8", "fail", "no rust/buggy*.rs")
    terminal = cli.read_terminal(task_dir)
    programs = [fixed, *buggy]
    schema_error = _expect_schema_error(task_dir, programs)
    if schema_error:
        return _row("V8", "fail", schema_error)
    factory = oracle_factory or cli.default_oracle_factory(timeout=120.0)
    try:
        oracle = factory(task_dir, terminal)
    except Exception as exc:  # a missing tool surfaces as an oracle result, not this
        return _row("V8", "fail", str(exc))
    expect = _read_json(task_dir / "rust" / "expect.json")
    notes = []
    for path in programs:
        source = path.read_text(encoding="utf-8")
        try:
            with tempfile.TemporaryDirectory(prefix="skelnet-bench-oracle-") as tmp:
                result = oracle.evaluate(source, Path(tmp))
        except Exception as exc:
            return _row("V8", "fail", f"{path.name}: {exc}")
        want_ok = path.name == "fixed.rs"
        got = getattr(result, "functional_ok", None)
        if got is not want_ok:
            return _row("V8", "fail", f"{path.name} functional_ok={got}, expected {want_ok}")
        spec = expect.get(path.name) if isinstance(expect, dict) else None
        if not isinstance(spec, dict) or "layer" not in spec:
            continue
        layers = getattr(result, "layers", None)
        if not layers:
            return _row("V8", "fail", f"{path.name} result has no layers")
        layer_name = spec.get("layer")
        layer = layers.get(layer_name) if isinstance(layers, dict) else None
        if layer is None:
            return _row("V8", "fail", f"{path.name} has no layer {layer_name}")
        status = getattr(layer, "status", None)
        category = getattr(layer, "category", None)
        if isinstance(layer, dict):
            status = layer.get("status")
            category = layer.get("category")
        if status != "fail" or category != spec.get("category"):
            return _row("V8", "fail",
                        f"{path.name} {layer_name} status={status} category={category}, "
                        f"expected fail/{spec.get('category')}")
        notes.append(f"{path.name} {layer_name}/{category}")
    return _row("V8", "pass", "; ".join(notes) or "functional_ok matches")


def _expect_schema_error(task_dir: Path, programs: list[Path]) -> str | None:
    path = task_dir / "rust" / "expect.json"
    if not path.is_file():
        return "expect.json is missing"
    try:
        data = _read_json(path)
    except json.JSONDecodeError as exc:
        return f"expect.json is not JSON: {exc}"
    if not isinstance(data, dict):
        return "expect.json must be an object"
    if data.get("schema_version") != "skelnet-rust-expect-v1":
        return "schema_version must be skelnet-rust-expect-v1"
    names = {item.name for item in programs}
    keys = {key for key in data if key != "schema_version"}
    if keys != names:
        missing = sorted(names - keys)
        extra = sorted(keys - names)
        return f"expect.json entries missing={missing} extra={extra}"
    fixed = data.get("fixed.rs")
    if not isinstance(fixed, dict) or fixed.get("functional") is not True:
        return "fixed.rs functional must be true"
    for name in sorted(names - {"fixed.rs"}):
        spec = data.get(name)
        if not isinstance(spec, dict) or spec.get("functional") is not False:
            return f"{name} functional must be false"
        layer = spec.get("layer")
        category = spec.get("category")
        if layer not in _LAYER_CATEGORIES:
            return f"{name} layer must be one of O1, O2, O3, O4"
        if category not in _LAYER_CATEGORIES[layer]:
            return f"{name} category {category} is not valid for {layer}"
    return None


def _protocol_params_error(value: Any) -> str | None:
    if not isinstance(value, dict) or not value:
        return "protocol_params must be an object of integers >= 2"
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            return "protocol_params keys must be names"
        if not isinstance(item, int) or isinstance(item, bool) or item < 2:
            return "protocol_params values must be integers >= 2"
    return None


def _v9(root: Path, task_dir: Path, rel: str) -> dict:
    manifest_path = root / "benchmarks" / "MANIFEST.json"
    if not manifest_path.is_file():
        return _row("V9", "fail", "MANIFEST.json is missing")
    try:
        manifest = _read_json(manifest_path)
    except json.JSONDecodeError as exc:
        return _row("V9", "fail", f"MANIFEST.json is not JSON: {exc}")
    records = [row for row in (manifest.get("files") or []) if row.get("task") == rel]
    by_file = {row.get("file"): row for row in records}
    for row in records:
        rel_file = row.get("file")
        if not isinstance(rel_file, str):
            return _row("V9", "fail", "MANIFEST record has no file")
        path = task_dir / rel_file
        if not path.is_file():
            return _row("V9", "fail", f"MANIFEST lists missing {rel_file}")
        digest = sha256_file(path)
        if digest != row.get("sha256"):
            return _row("V9", "fail", f"sha256 mismatch for {rel_file}")
    required = []
    h1 = task_dir / "REQUIREMENTS.h1.md"
    if h1.is_file():
        required.append("REQUIREMENTS.h1.md")
    rust = task_dir / "rust"
    if rust.is_dir():
        for path in sorted(rust.iterdir()):
            if path.is_file():
                required.append(f"rust/{path.name}")
    missing = [name for name in required if name not in by_file]
    if missing:
        return _row("V9", "fail", "MANIFEST missing " + ", ".join(missing))
    return _row("V9", "pass", f"{len(records)} MANIFEST records match")


def tier_repo(root: Path | str, pattern: str = "all", *, write: bool = False,
              tools=None, tasks: list[Path] | None = None) -> dict:
    """Compute tiers for main tasks. Boundary tasks are omitted."""
    root = Path(root)
    if tasks is None:
        tasks, _unmatched = _select_patterns(root, pattern)
    tools = tools if tools is not None else RealTools()
    baseline_ids = set(_load_tasks(root / "benchmarks" / "BASELINE.json"))
    rows = []
    for task_dir in tasks:
        rel = str(task_dir.relative_to(root / "benchmarks" / "tasks"))
        if _is_boundary(rel):
            continue
        try:
            rows.append(_tier_one(root, task_dir, rel, baseline_ids=baseline_ids,
                                  tools=tools, write=write))
        except Exception as exc:
            rows.append({
                "task": rel,
                "metrics": {"computed_tier": None, "nearest_tier": None, "violations": []},
                "computed_tier": None,
                "nearest_tier": None,
                "declared_tier": "unclassified",
                "tier_source": "unclassified",
                "violations": [f"{type(exc).__name__}: {exc}"],
                "error": f"{type(exc).__name__}: {exc}",
            })
    report = _tier_report(rows)
    if write:
        _write_tiers_md(root, report)
    return report


def _tier_report(rows: list[dict]) -> dict:
    declared_counts: dict[str, int] = {}
    computed_counts: dict[str, int] = {}
    for row in rows:
        declared_counts[row["declared_tier"]] = declared_counts.get(row["declared_tier"], 0) + 1
        computed = row["computed_tier"] or "unclassified"
        computed_counts[computed] = computed_counts.get(computed, 0) + 1
    mismatches = [row["task"] for row in rows if row["computed_tier"] != row["declared_tier"]]
    nearest = [row["task"] for row in rows if row.get("tier_source") == "nearest"]
    legacy_outside = [row["task"] for row in rows if row.get("legacy_outside_baseline")]
    return {"tasks": rows, "counts": declared_counts, "computed_counts": computed_counts,
            "mismatches": mismatches, "nearest": nearest,
            "legacy_outside_baseline": legacy_outside}


def _tier_one(root, task_dir, rel, *, baseline_ids, tools, write: bool) -> dict:
    cir_path = task_dir / "gold.cir.json"
    cir = {}
    if cir_path.is_file():
        try:
            cir = _read_json(cir_path)
        except json.JSONDecodeError:
            cir = {}
    reqs = {}
    req_path = task_dir / "requirements.json"
    if req_path.is_file():
        try:
            loaded = _read_json(req_path)
            if isinstance(loaded, dict):
                reqs = loaded
        except json.JSONDecodeError:
            reqs = {}
    parameterized = _protocol_params_error(reqs["protocol_params"]) is None if (
        "protocol_params" in reqs) else False
    metrics = metrics_from_cir(cir if isinstance(cir, dict) else {},
                               parameterized=parameterized)
    states, source, note, complete = _state_count(root, task_dir, rel, tools)
    metrics["states"] = states
    metrics["states_source"] = source
    metrics["states_complete"] = complete
    if note:
        metrics["states_note"] = note
    computed, nearest, violations = classify_tier(
        metrics["threads"], metrics["sync_resources"], metrics["mechanism_count"],
        states, parameterized, states_complete=complete)
    legacy, declared_legacy = _legacy_declaration(rel, baseline_ids, reqs)
    if legacy:
        declared, tier_source = declared_legacy, "legacy"
    elif computed:
        declared, tier_source = computed, "computed"
    elif nearest and len(violations) == 1 and not any(item.startswith("states") for item in violations):
        declared, tier_source = nearest, "nearest"
    else:
        declared, tier_source = "unclassified", "unclassified"
    metrics["computed_tier"] = computed
    metrics["nearest_tier"] = nearest
    metrics["violations"] = violations
    if write:
        _write_requirement_tier(task_dir, declared, tier_source, metrics, legacy=legacy)
    return {"task": rel, "metrics": metrics, "computed_tier": computed,
            "nearest_tier": nearest, "declared_tier": declared,
            "tier_source": tier_source, "violations": violations,
            "legacy_outside_baseline": legacy and rel not in baseline_ids}


def _legacy_declaration(rel: str, baseline_ids: set[str], reqs: dict) -> tuple[bool, str]:
    """Baseline tasks, and explicit legacy declarations, keep a fixed tier."""
    explicit = reqs.get("tier_source") == "legacy" and reqs.get("tier") in _TIERS
    if rel in baseline_ids or explicit:
        if explicit:
            return True, str(reqs["tier"])
        return True, "L1"
    return False, ""


def metrics_from_cir(cir: dict, *, parameterized: bool = False) -> dict:
    """Thread and resource counts from a gold ConcIR document.

    Each ``spawn`` node and each entry of ``scope.funcs`` is one thread, even
    when the function name repeats. ``main`` is not counted. A spawn that sits
    in a loop is still one node, so the concurrency of that loop is 1.
    ``parameterized`` is not inferred from the CIR; the caller supplies it.
    """
    spawned: list[str] = []
    declared: list[tuple[str, str, str]] = []
    references: set[str] = set()
    paired_locks: set[str] = set()
    for module in cir.get("modules") or []:
        if not isinstance(module, dict):
            continue
        mod = str(module.get("name") or "")
        for resource in module.get("resources") or []:
            if not isinstance(resource, dict):
                continue
            name = resource.get("name")
            typ = resource.get("type")
            if isinstance(name, str) and typ in SYNC_TYPES and "sid" not in resource:
                declared.append((mod, name, typ))
        for node in _walk(module):
            if not isinstance(node, dict) or "kind" not in node:
                continue
            kind = node.get("kind")
            if kind == "spawn" and isinstance(node.get("func"), str):
                if not _is_main(node["func"]):
                    spawned.append(node["func"])
            elif kind == "scope":
                for func in node.get("funcs") or []:
                    if isinstance(func, str) and not _is_main(func):
                        spawned.append(func)
            if kind == "condvar_wait" and isinstance(node.get("lock"), str):
                paired_locks.add(node["lock"])
            for field in _REF_FIELDS:
                value = node.get(field)
                if isinstance(value, str):
                    references.add(value)
    used = []
    unused = []
    for mod, name, typ in declared:
        if _resource_used(mod, name, references):
            used.append((mod, name, typ))
        else:
            unused.append(f"{mod}::{name}" if mod else name)
    mechanisms = _mechanisms(used, paired_locks)
    return {"threads": len(spawned),
            "thread_funcs": sorted(set(spawned)),
            "sync_resources": len(used),
            "unused_resources": unused,
            "mechanisms": mechanisms,
            "mechanism_count": len(mechanisms),
            "parameterized": parameterized}


def _is_main(func: str) -> bool:
    return func == "main" or func.endswith("::main")


def _resource_used(module: str, name: str, references: set[str]) -> bool:
    aliases = {name}
    if module:
        aliases.add(f"{module}::{name}")
    if name in references or f"{module}::{name}" in references:
        return True
    return any(ref == name or ref.endswith(f"::{name}") for ref in references)


def _mechanisms(used: list[tuple[str, str, str]], paired_locks: set[str]) -> list[str]:
    """Condvar plus the mutex it waits on is one mechanism."""
    found: set[str] = set()
    has_unpaired_mutex = False
    has_condvar = False
    for module, name, typ in used:
        if typ == "Condvar":
            has_condvar = True
        elif typ == "Mutex":
            if not any(_resource_used(module, name, {lock}) for lock in paired_locks):
                has_unpaired_mutex = True
        else:
            found.add(typ)
    if has_condvar:
        found.add("Condvar")
    if has_unpaired_mutex:
        found.add("Mutex")
    return sorted(found)


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def classify_tier(threads: int, sync_resources: int, mechanism_count: int,
                  states: int | None, parameterized: bool, *,
                  states_complete: bool = True) -> tuple[str | None, str, list[str]]:
    """Lowest fully matching tier, the nearest tier, and that tier's violations.

    A missing or incomplete state count fails every state condition. ``nearest``
    is the tier with the fewest violations; ties take the lower tier.
    """
    def state_ok(predicate) -> bool:
        return states_complete and states is not None and predicate

    ladders = (
        ("L1", [
            ("threads in 0..3", 0 <= threads <= 3),
            ("sync_resources<=2 and mechanisms<=1",
             sync_resources <= 2 and mechanism_count <= 1),
            ("states<=300", state_ok(states is not None and states <= 300)),
        ]),
        ("L2", [
            ("threads in 3..4", 3 <= threads <= 4),
            ("mechanisms>=2 or sync_resources>=3",
             mechanism_count >= 2 or sync_resources >= 3),
            ("states in 300..5000", state_ok(states is not None and 300 <= states <= 5000)),
        ]),
        ("L3", [
            ("threads in 4..6", 4 <= threads <= 6),
            ("mechanisms>=3 or protocol_params", mechanism_count >= 3 or parameterized),
            ("states in 5000..100000",
             state_ok(states is not None and 5000 <= states <= 100_000)),
        ]),
    )
    computed = None
    nearest = "L1"
    nearest_bad: list[str] = []
    best = None
    for _index, (name, conds) in enumerate(ladders):
        bad = [label for label, ok in conds if not ok]
        if not bad and computed is None:
            computed = name
        # Count only. A tie does not replace the earlier tier, so the lower
        # tier wins. ``<=`` would keep the later tier instead.
        rank = len(bad)
        if best is None or rank < best:
            best = rank
            nearest = name
            nearest_bad = bad
    return computed, nearest, nearest_bad


def _state_count(root: Path, task_dir: Path, rel: str, tools
                 ) -> tuple[int | None, str, str, bool]:
    """Return states, source, note, and whether the count is complete."""
    skel = task_dir / "gold.skel"
    contract = task_dir / "contract.json"
    error = None
    if skel.is_file():
        lowered, error = tools.lower_json(skel)
        if lowered is not None:
            with tempfile.TemporaryDirectory(prefix="skelnet-bench-tier-") as tmp:
                cir_path = Path(tmp) / "gold.cir.json"
                cir_path.write_text(json.dumps(lowered), encoding="utf-8")
                payload, explore_error = tools.explore(
                    cir_path, contract if contract.is_file() else None)
            if isinstance(explore_error, ToolUnavailable):
                error = explore_error
            elif isinstance(payload, dict) and payload.get("complete") is True and isinstance(
                    payload.get("states_explored"), int):
                return payload["states_explored"], "explore", "", True
            elif isinstance(payload, dict):
                limit = payload.get("states_explored")
                note = f"incomplete ({limit})" if limit is not None else "incomplete"
                count = limit if isinstance(limit, int) else None
                return count, "explore", note, False
            else:
                error = explore_error or error
    else:
        error = "gold.skel is missing"
    entry = _baseline_entry(root, rel, _deviations(root))
    if entry and isinstance(entry.get("states_explored_reference"), int):
        note = "fell back to states_explored_reference"
        if error:
            note = f"{note} ({error})"
        return entry["states_explored_reference"], "baseline", note, True
    return None, "unavailable", str(error) if error else "no state count", False


def _write_requirement_tier(task_dir: Path, tier: str, source: str, metrics: dict, *,
                            legacy: bool) -> None:
    path = task_dir / "requirements.json"
    if not path.is_file():
        return
    data = _read_json(path)
    if not isinstance(data, dict):
        return
    data.pop("tier_metrics", None)
    if not legacy:
        data.pop("tier", None)
        data.pop("tier_source", None)
        data["tier"] = tier
        data["tier_source"] = source
    data["tier_metrics"] = metrics
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_tiers_md(root: Path, report: dict) -> None:
    path = root / "benchmarks" / "TIERS.md"
    path.write_text(_tiers_markdown(report), encoding="utf-8")


def _validate_markdown(report: dict) -> str:
    lines = []
    for task in report["tasks"]:
        lines.append(f"## {task['task']}")
        for check in task["checks"]:
            lines.append(f"- {check['id']} {check['status']}: {check['reason']}")
    lines.append(f"\nfail_count: {report['fail_count']}")
    return "\n".join(lines) + "\n"


def _tiers_markdown(report: dict) -> str:
    lines = ["| task | threads | sync | mechanisms | states | computed | nearest | violations | declared | source |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in report["tasks"]:
        metrics = row.get("metrics") or {}
        mechs = ",".join(metrics.get("mechanisms") or [])
        violations = ", ".join(row.get("violations") or [])
        lines.append(
            f"| {row['task']} | {metrics.get('threads')} | {metrics.get('sync_resources')} | "
            f"{mechs} | {metrics.get('states')} | {row.get('computed_tier')} | "
            f"{row.get('nearest_tier')} | {violations} | {row['declared_tier']} | "
            f"{row['tier_source']} |")
    lines.append("")
    lines.append("## declared counts")
    for name in ("L1", "L2", "L3", "unclassified"):
        count = (report.get("counts") or {}).get(name)
        if count:
            lines.append(f"- {name}: {count}")
    lines.append("")
    lines.append("## computed counts")
    for name in ("L1", "L2", "L3", "unclassified"):
        count = (report.get("computed_counts") or {}).get(name)
        if count:
            lines.append(f"- {name}: {count}")
    mismatches = report.get("mismatches") or []
    lines.append("")
    lines.append("## declared != computed")
    by_task = {row["task"]: row for row in report["tasks"]}
    if not mismatches:
        lines.append("- (none)")
    else:
        for task in mismatches:
            row = by_task.get(task)
            if row is None:
                lines.append(f"- {task}")
            else:
                lines.append(
                    f"- {task}: declared {row['declared_tier']}, computed {row['computed_tier']}")
    lines.append("")
    lines.append("## tier_source nearest")
    nearest = report.get("nearest") or []
    if not nearest:
        lines.append("- (none)")
    else:
        for task in nearest:
            row = by_task.get(task) or {}
            lines.append(f"- {task}: {', '.join(row.get('violations') or [])}")
    outside = report.get("legacy_outside_baseline") or []
    lines.append("")
    lines.append("## legacy outside BASELINE.json")
    if not outside:
        lines.append("- (none)")
    else:
        for task in outside:
            lines.append(f"- {task}")
    return "\n".join(lines) + "\n"


def _load_tasks(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    try:
        doc = _read_json(path)
    except json.JSONDecodeError:
        return {}
    return {row["task"]: row for row in (doc.get("tasks") or []) if isinstance(row, dict) and row.get("task")}


def _baseline_entry(root: Path, rel: str, devs: list[dict]) -> dict | None:
    entries = _load_tasks(root / "benchmarks" / "BASELINE.json")
    ext = _load_tasks(root / "benchmarks" / "BASELINE_EXT.json")
    for task, row in ext.items():
        entries.setdefault(task, row)
    if rel in entries:
        return entries[rel]
    for dev in devs:
        other = None
        if dev.get("moved_to") == rel:
            other = dev.get("task")
        elif dev.get("task") == rel and dev.get("moved_to"):
            other = dev.get("moved_to")
        if other in entries:
            return entries[other]
    return None


def _deviations(root: Path) -> list[dict]:
    path = root / "benchmarks" / "DEVIATIONS.json"
    if not path.is_file():
        return []
    try:
        doc = _read_json(path)
    except json.JSONDecodeError:
        return []
    return [row for row in (doc.get("deviations") or []) if isinstance(row, dict)]


def _unmigrated_deviation(devs: list[dict], rel: str) -> bool:
    for dev in devs:
        if dev.get("kind") != "baseline_deviation":
            continue
        if dev.get("moved_to"):
            continue
        if dev.get("task") == rel or dev.get("moved_to") == rel:
            return True
    return False


def _allowlist(root: Path) -> dict:
    path = root / "benchmarks" / "terminal_allowlist.json"
    if not path.is_file():
        return {}
    try:
        doc = _read_json(path)
    except json.JSONDecodeError:
        return {}
    return doc if isinstance(doc, dict) else {}


def _literal_lines(source: str) -> list[str]:
    lines: list[str] = []
    for kind, text in _scan(source):
        if kind == "string":
            lines.extend(text.split("\n"))
    return lines


def _print_formats(source: str) -> list[str]:
    """Format strings of println!/print!/writeln!/write!, ignoring comments."""
    tokens = list(_scan(source))
    formats: list[str] = []
    index = 0
    while index < len(tokens):
        kind, text = tokens[index]
        if (kind == "ident" and text in _PRINT_MACROS and index + 1 < len(tokens)
                and tokens[index + 1] == ("punct", "!")):
            cursor = index + 2
            if cursor < len(tokens) and tokens[cursor] == ("punct", "("):
                depth = 0
                first = None
                while cursor < len(tokens):
                    token = tokens[cursor]
                    if token == ("punct", "("):
                        depth += 1
                    elif token == ("punct", ")"):
                        depth -= 1
                        if depth == 0:
                            break
                    elif token[0] == "string" and first is None:
                        first = token[1]
                    cursor += 1
                if first is not None:
                    formats.append(first)
                index = cursor
                continue
        index += 1
    return formats


def _scan(source: str):
    """Tokens outside comments: idents, punctuation, and decoded strings."""
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        if char.isspace():
            index += 1
            continue
        if char == "/" and index + 1 < length and source[index + 1] == "/":
            newline = source.find("\n", index)
            index = length if newline < 0 else newline + 1
            continue
        if char == "/" and index + 1 < length and source[index + 1] == "*":
            end = source.find("*/", index + 2)
            index = length if end < 0 else end + 2
            continue
        if char == "r" and _raw_string_at(source, index):
            decoded, index = _read_raw_string(source, index)
            yield ("string", decoded)
            continue
        if char == '"':
            decoded, index = _read_cooked_string(source, index)
            yield ("string", decoded)
            continue
        if char == "'":
            index = _skip_char_literal(source, index)
            continue
        if char.isalpha() or char == "_":
            end = index + 1
            while end < length and (source[end].isalnum() or source[end] == "_"):
                end += 1
            yield ("ident", source[index:end])
            index = end
            continue
        yield ("punct", char)
        index += 1


def _raw_string_at(source: str, index: int) -> bool:
    if source[index] != "r":
        return False
    cursor = index + 1
    while cursor < len(source) and source[cursor] == "#":
        cursor += 1
    return cursor < len(source) and source[cursor] == '"'


def _read_raw_string(source: str, index: int) -> tuple[str, int]:
    cursor = index + 1
    hashes = 0
    while cursor < len(source) and source[cursor] == "#":
        hashes += 1
        cursor += 1
    if cursor >= len(source) or source[cursor] != '"':
        return "", index + 1
    cursor += 1
    closer = '"' + ("#" * hashes)
    end = source.find(closer, cursor)
    if end < 0:
        return source[cursor:], len(source)
    return source[cursor:end], end + len(closer)


def _read_cooked_string(source: str, index: int) -> tuple[str, int]:
    chars: list[str] = []
    cursor = index + 1
    length = len(source)
    while cursor < length:
        char = source[cursor]
        if char == "\\":
            decoded, cursor = _decode_escape(source, cursor)
            chars.append(decoded)
            continue
        if char == '"':
            return "".join(chars), cursor + 1
        chars.append(char)
        cursor += 1
    return "".join(chars), length


def _decode_escape(source: str, index: int) -> tuple[str, int]:
    if index + 1 >= len(source):
        return "\\", index + 1
    name = source[index + 1]
    simple = {"n": "\n", "t": "\t", "\\": "\\", '"': '"', "'": "'", "0": "\0", "r": "\r"}
    if name in simple:
        return simple[name], index + 2
    if name == "u" and index + 2 < len(source) and source[index + 2] == "{":
        end = source.find("}", index + 3)
        if end > index + 3:
            try:
                return chr(int(source[index + 3:end], 16)), end + 1
            except ValueError:
                pass
    return name, index + 2


def _skip_char_literal(source: str, index: int) -> int:
    cursor = index + 1
    length = len(source)
    while cursor < length:
        if source[cursor] == "\\":
            cursor += 2
            continue
        if source[cursor] == "'":
            return cursor + 1
        cursor += 1
    return length


def _is_format_hole(inner: str) -> bool:
    argument, _sep, _rest = inner.partition(":")
    return argument == "" or argument.isdigit() or argument.isidentifier()


def _has_placeholder(fmt: str) -> bool:
    index = 0
    while index < len(fmt):
        if fmt[index] == "{" and index + 1 < len(fmt) and fmt[index + 1] == "{":
            index += 2
            continue
        if fmt[index] == "}" and index + 1 < len(fmt) and fmt[index + 1] == "}":
            index += 2
            continue
        if fmt[index] == "{":
            end = fmt.find("}", index + 1)
            if end < 0:
                return False
            if _is_format_hole(fmt[index + 1:end]):
                return True
            index = end + 1
            continue
        index += 1
    return False


def _format_matches_terminal(fmt: str, terminal: str) -> bool:
    """True when placeholders can cover the whole terminal line."""
    if not _has_placeholder(fmt):
        return False
    parts: list[str] = []
    index = 0
    while index < len(fmt):
        if fmt[index] == "{" and index + 1 < len(fmt) and fmt[index + 1] == "{":
            parts.append(re.escape("{"))
            index += 2
            continue
        if fmt[index] == "}" and index + 1 < len(fmt) and fmt[index + 1] == "}":
            parts.append(re.escape("}"))
            index += 2
            continue
        if fmt[index] == "{":
            end = fmt.find("}", index + 1)
            if end > index and _is_format_hole(fmt[index + 1:end]):
                parts.append(".*")
                index = end + 1
                continue
        parts.append(re.escape(fmt[index]))
        index += 1
    return re.fullmatch("".join(parts), terminal) is not None


def _frontend_error_message(stdout: str) -> str | None:
    try:
        payload = json.loads(stdout or "")
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list):
        return None
    codes = [str(item["code"]) for item in payload
             if isinstance(item, dict) and item.get("code")]
    shown = ", ".join(codes) if codes else "(no code)"
    return f"frontend errors: {shown}"


def _cargo_available() -> bool:
    from shutil import which
    return which("cargo") is not None


class RealTools:
    """skelnet / concir-backend adapter. Missing binaries become skip reasons."""

    def __init__(self) -> None:
        self._backend: Backend | None = None
        self._error: str | None = None
        try:
            self._backend = Backend()
        except FileNotFoundError as exc:
            self._error = str(exc)

    def _missing(self, what: str) -> ToolUnavailable:
        return ToolUnavailable(self._error or f"{what} binary is not available")

    def verify_skel(self, skel: Path, contract: Path):
        if self._backend is None:
            return None, self._missing("skelnet")
        try:
            result = self._backend.verify(skel, contract)
        except Exception as exc:
            message = _frontend_error_message(self._verify_stdout(skel, contract))
            if message:
                return None, message
            return None, f"{type(exc).__name__}: {exc}"
        if not isinstance(result.payload, dict):
            message = _frontend_error_message(getattr(result, "stdout", "") or "")
            if message:
                return None, message
            return None, result.error or "skelnet verify produced no JSON"
        return result.payload, None

    def _verify_stdout(self, skel: Path, contract: Path) -> str:
        proc = subprocess.run(
            [str(self._backend.skelnet), "verify", str(skel), str(contract),
             "--engine", "petri", "--json"],
            capture_output=True, text=True, timeout=self._backend.timeout)
        return proc.stdout or ""

    def check_skel(self, skel: Path):
        if self._backend is None:
            return None, [], self._missing("skelnet")
        try:
            result = self._backend.check(skel)
        except Exception as exc:
            return None, [], f"{type(exc).__name__}: {exc}"
        payload = result.payload if isinstance(result.payload, dict) else {}
        codes = []
        for item in payload.get("diagnostics") or []:
            if isinstance(item, dict) and item.get("code"):
                codes.append(str(item["code"]))
        return result.exit_code, codes, None

    def lower_json(self, skel: Path):
        if self._backend is None:
            return None, self._missing("skelnet")
        with tempfile.TemporaryDirectory(prefix="skelnet-bench-lower-") as tmp:
            dest = Path(tmp) / "lowered.cir.json"
            result = self._backend.lower(skel, dest)
            if result.exit_code != 0 or not dest.is_file():
                return None, result.error or "skelnet lower failed"
            try:
                return _read_json(dest), None
            except json.JSONDecodeError as exc:
                return None, f"lower output is not JSON: {exc}"

    def explore(self, cir: Path, contract: Path | None):
        if self._backend is None:
            return None, self._missing("concir-backend")
        target = contract if contract is not None else cir
        # verify_cir always wants a contract path. An absent contract still has
        # to be a path the backend can skip; pass the cir path only when the
        # caller has a contract.
        if contract is None:
            return None, "contract.json is missing"
        result = self._backend.verify_cir(cir, target)
        if not isinstance(result.payload, dict):
            return None, result.error or "concir-backend explore produced no JSON"
        return result.payload, None
