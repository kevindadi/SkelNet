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
import tempfile
from pathlib import Path
from typing import Any, Callable

from .backend import Backend, repo_root, sha256_file

CHECKS = ("V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9")
SYNC_TYPES = ("Mutex", "Condvar", "Semaphore", "Channel", "Atomic")
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
    checks = _parse_checks(args.checks)
    report = validate_repo(
        root, args.tasks, checks=checks, run=bool(args.run),
        oracle=bool(args.oracle), strict=bool(args.strict))
    _emit(report, json_out=bool(args.json), kind="validate")
    return 1 if any(c["status"] == "fail" for task in report["tasks"] for c in task["checks"]) else 0


def cmd_tiers(args) -> int:
    root = Path(args.root) if args.root else repo_root()
    report = tier_repo(root, args.tasks, write=bool(args.write))
    _emit(report, json_out=bool(args.json), kind="tiers")
    return 0


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
                  tools=None, oracle_factory: Callable | None = None) -> dict:
    """Run the selected checks. ``tools`` and ``oracle_factory`` are test hooks."""
    from . import cli
    root = Path(root)
    tasks = cli._select_tasks(root, pattern)
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
    hints = data.get("hint_variants")
    if hints is not None:
        names = list(hints) if isinstance(hints, dict) else list(hints)
        if not isinstance(hints, (dict, list)):
            return _row("V2", "fail", "hint_variants must be a list or object")
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
    if error and payload is None:
        if "not found" in error or "No such file" in error:
            return _row("V4", "skip", error)
        return _row("V4", "fail", error)
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
        if error and payload is None:
            if "not found" in error or "No such file" in error:
                return _row("V4", "skip", error)
            return _row("V4", "fail", error)
        compared = _compare_baseline("V4", entry, payload)
        if compared["status"] != "pass":
            return compared
        reasons.append("gold.cir.json matches BASELINE")
    if direct.is_file():
        code, codes, error = tools.check_skel(direct)
        if error:
            if "not found" in error or "No such file" in error:
                return _row("V4", "skip", error)
            return _row("V4", "fail", error)
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
    if error and lowered is None:
        if "not found" in error or "No such file" in error:
            return _row("V5", "skip", error)
        return _row("V5", "fail", error)
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
    literals = _string_literals(source)
    if any(literal == terminal for literal in literals):
        return _row("V6", "fail", "expected terminal line appears as a string literal")
    prints = _print_formats(source)
    if not any(_has_placeholder(fmt) for fmt in prints):
        return _row("V6", "fail", "no println!/print! with a format argument")
    return _row("V6", "pass", "terminal line is computed, not a literal")


def _v7(task_dir: Path, rel: str) -> dict:
    from . import cli
    from .oracle import CONCIR_SYNC_CRATE, cargo_toml, repo_toolchain_channel
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
    if run.returncode != 0:
        return _row("V7", "fail", f"exit {run.returncode}")
    last = _last_nonempty(run.stdout)
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
    factory = oracle_factory or cli.default_oracle_factory(timeout=120.0)
    try:
        oracle = factory(task_dir, terminal)
    except Exception as exc:  # a missing tool surfaces as an oracle result, not this
        return _row("V8", "fail", str(exc))
    expect = {}
    expect_path = task_dir / "rust" / "expect.json"
    if expect_path.is_file():
        try:
            expect = _read_json(expect_path)
        except json.JSONDecodeError as exc:
            return _row("V8", "fail", f"expect.json is not JSON: {exc}")
    notes = []
    layer_skipped = False
    programs = [(fixed, True)] + [(path, False) for path in buggy]
    for path, want_ok in programs:
        source = path.read_text(encoding="utf-8")
        try:
            with tempfile.TemporaryDirectory(prefix="skelnet-bench-oracle-") as tmp:
                result = oracle.evaluate(source, Path(tmp))
        except Exception as exc:
            return _row("V8", "fail", f"{path.name}: {exc}")
        got = getattr(result, "functional_ok", None)
        if got is not want_ok:
            return _row("V8", "fail", f"{path.name} functional_ok={got}, expected {want_ok}")
        spec = expect.get(path.name) if isinstance(expect, dict) else None
        layers = getattr(result, "layers", None)
        if not isinstance(spec, dict) or "layer" not in spec:
            continue
        if not layers:
            layer_skipped = True
            continue
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
    if layer_skipped:
        notes.append("layer check skipped (no layers)")
    return _row("V8", "pass", "; ".join(notes) or "functional_ok matches")


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
              tools=None) -> dict:
    """Compute tiers for main tasks. Boundary tasks are omitted."""
    from . import cli
    root = Path(root)
    tools = tools if tools is not None else RealTools()
    ext = set(_load_tasks(root / "benchmarks" / "BASELINE_EXT.json"))
    rows = []
    for task_dir in cli._select_tasks(root, pattern):
        rel = str(task_dir.relative_to(root / "benchmarks" / "tasks"))
        if _is_boundary(rel):
            continue
        rows.append(_tier_one(root, task_dir, rel, ext=ext, tools=tools, write=write))
    if write:
        _write_tiers_md(root, rows)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["declared_tier"]] = counts.get(row["declared_tier"], 0) + 1
    mismatches = [row for row in rows if row["computed_tier"] != row["declared_tier"]]
    return {"tasks": rows, "counts": counts,
            "mismatches": [row["task"] for row in mismatches]}


def _tier_one(root, task_dir, rel, *, ext, tools, write: bool) -> dict:
    cir_path = task_dir / "gold.cir.json"
    cir = {}
    if cir_path.is_file():
        try:
            cir = _read_json(cir_path)
        except json.JSONDecodeError:
            cir = {}
    metrics = metrics_from_cir(cir if isinstance(cir, dict) else {})
    states, source, note = _state_count(root, task_dir, rel, tools)
    metrics["states"] = states
    metrics["states_source"] = source
    if note:
        metrics["states_note"] = note
    computed, violations = classify_tier(
        metrics["threads"], metrics["sync_resources"], metrics["mechanism_count"],
        states, metrics["parameterized"])
    if rel in ext:
        declared, tier_source = computed, "computed"
    else:
        declared, tier_source = "L1", "legacy"
    if write:
        _write_requirement_tier(task_dir, declared, tier_source, metrics)
    return {"task": rel, "metrics": metrics, "computed_tier": computed,
            "declared_tier": declared, "tier_source": tier_source,
            "violations": violations}


def metrics_from_cir(cir: dict) -> dict:
    """Thread, resource, and mechanism counts from a gold ConcIR document."""
    threads: set[str] = set()
    resources: list[dict] = []
    for node in _walk(cir):
        if not isinstance(node, dict):
            continue
        kind = node.get("kind")
        if kind == "spawn" and isinstance(node.get("func"), str):
            threads.add(node["func"])
        elif kind == "scope":
            for func in node.get("funcs") or []:
                if isinstance(func, str):
                    threads.add(func)
        elif (node.get("type") in SYNC_TYPES and isinstance(node.get("name"), str)
              and "sid" not in node):
            resources.append(node)
    mechanisms = sorted({res["type"] for res in resources})
    parameterized = any(_parameterized(res) for res in resources)
    return {"threads": len(threads), "sync_resources": len(resources),
            "mechanisms": mechanisms, "mechanism_count": len(mechanisms),
            "parameterized": parameterized}


def _parameterized(resource: dict) -> bool:
    count = resource.get("count")
    if isinstance(count, int) and count != 1:
        return True
    for key in ("capacity", "bound"):
        if isinstance(resource.get(key), int):
            return True
    return False


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def classify_tier(threads: int, sync_resources: int, mechanism_count: int,
                  states: int | None, parameterized: bool) -> tuple[str, list[str]]:
    """Lowest tier whose conditions all hold, else ``unclassified``."""
    def states_in(low: int, high: int) -> bool:
        return states is not None and low <= states <= high

    ladders = (
        ("L1", [
            ("threads<=3", threads <= 3),
            ("sync_resources<=2", sync_resources <= 2),
            ("mechanisms==1", mechanism_count == 1),
            ("states<=300", states is not None and states <= 300),
        ]),
        ("L2", [
            ("threads in 3..4", 3 <= threads <= 4),
            ("mechanisms==2", mechanism_count == 2),
            ("states in 300..5000", states_in(300, 5000)),
        ]),
        ("L3", [
            ("threads in 4..6", 4 <= threads <= 6),
            ("mechanisms>=3 or parameterized", mechanism_count >= 3 or parameterized),
            ("states in 5000..100000", states_in(5000, 100_000)),
        ]),
    )
    failed: list[str] = []
    for name, conds in ladders:
        bad = [label for label, ok in conds if not ok]
        if not bad:
            return name, []
        failed.extend(f"{name}:{label}" for label in bad)
    if states is None:
        failed.append("states unavailable")
    return "unclassified", failed


def _state_count(root: Path, task_dir: Path, rel: str, tools) -> tuple[int | None, str, str]:
    skel = task_dir / "gold.skel"
    contract = task_dir / "contract.json"
    if skel.is_file():
        lowered, error = tools.lower_json(skel)
        if lowered is not None:
            with tempfile.TemporaryDirectory(prefix="skelnet-bench-tier-") as tmp:
                cir_path = Path(tmp) / "gold.cir.json"
                cir_path.write_text(json.dumps(lowered), encoding="utf-8")
                payload, explore_error = tools.explore(
                    cir_path, contract if contract.is_file() else None)
            if isinstance(payload, dict) and isinstance(payload.get("states_explored"), int):
                return payload["states_explored"], "explore", ""
            error = explore_error or error
    else:
        error = "gold.skel is missing"
    entry = _baseline_entry(root, rel, _deviations(root))
    if entry and isinstance(entry.get("states_explored_reference"), int):
        note = "fell back to states_explored_reference"
        if error:
            note = f"{note} ({error})"
        return entry["states_explored_reference"], "baseline", note
    return None, "unavailable", error or "no state count"


def _write_requirement_tier(task_dir: Path, tier: str, source: str, metrics: dict) -> None:
    path = task_dir / "requirements.json"
    if not path.is_file():
        return
    data = _read_json(path)
    if not isinstance(data, dict):
        return
    for key in ("tier", "tier_source", "tier_metrics"):
        data.pop(key, None)
    data["tier"] = tier
    data["tier_source"] = source
    data["tier_metrics"] = metrics
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_tiers_md(root: Path, rows: list[dict]) -> None:
    path = root / "benchmarks" / "TIERS.md"
    path.write_text(_tiers_markdown({"tasks": rows, "counts": {},
                                    "mismatches": []}), encoding="utf-8")


def _validate_markdown(report: dict) -> str:
    lines = []
    for task in report["tasks"]:
        lines.append(f"## {task['task']}")
        for check in task["checks"]:
            lines.append(f"- {check['id']} {check['status']}: {check['reason']}")
    lines.append(f"\nfail_count: {report['fail_count']}")
    return "\n".join(lines) + "\n"


def _tiers_markdown(report: dict) -> str:
    lines = ["| task | threads | sync | mechanisms | states | computed | declared | source |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in report["tasks"]:
        metrics = row["metrics"]
        mechs = ",".join(metrics.get("mechanisms") or [])
        lines.append(
            f"| {row['task']} | {metrics.get('threads')} | {metrics.get('sync_resources')} | "
            f"{mechs} | {metrics.get('states')} | {row['computed_tier']} | "
            f"{row['declared_tier']} | {row['tier_source']} |")
    counts = report.get("counts") or {}
    if not counts:
        counts = {}
        for row in report["tasks"]:
            counts[row["declared_tier"]] = counts.get(row["declared_tier"], 0) + 1
    lines.append("")
    lines.append("## counts")
    for name in ("L1", "L2", "L3", "unclassified"):
        if name in counts:
            lines.append(f"- {name}: {counts[name]}")
    mismatches = report.get("mismatches")
    if mismatches is None:
        mismatches = [row["task"] for row in report["tasks"]
                      if row["computed_tier"] != row["declared_tier"]]
    lines.append("")
    lines.append("## declared != computed")
    if not mismatches:
        lines.append("- (none)")
    else:
        by_task = {row["task"]: row for row in report["tasks"]}
        for task in mismatches:
            row = by_task.get(task)
            if row is None:
                lines.append(f"- {task}")
            else:
                lines.append(
                    f"- {task}: declared {row['declared_tier']}, computed {row['computed_tier']}")
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


def _string_literals(source: str) -> list[str]:
    out: list[str] = []
    index = 0
    length = len(source)
    while index < length:
        if source.startswith("//", index):
            newline = source.find("\n", index)
            index = length if newline < 0 else newline + 1
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            index = length if end < 0 else end + 2
            continue
        if source[index] != '"':
            index += 1
            continue
        chars: list[str] = []
        index += 1
        while index < length:
            char = source[index]
            if char == "\\":
                if index + 1 < length:
                    chars.append(source[index + 1])
                index += 2
                continue
            if char == '"':
                index += 1
                break
            chars.append(char)
            index += 1
        out.append("".join(chars))
    return out


def _print_formats(source: str) -> list[str]:
    formats = []
    for match in re.finditer(r"\b(?:println|print)!\s*\(", source):
        literal = _first_string(source[match.end():])
        if literal is not None:
            formats.append(literal)
    return formats


def _first_string(text: str) -> str | None:
    literals = _string_literals(text)
    return literals[0] if literals else None


def _has_placeholder(fmt: str) -> bool:
    index = 0
    while index < len(fmt):
        if fmt[index] != "{":
            index += 1
            continue
        if index + 1 < len(fmt) and fmt[index + 1] == "{":
            index += 2
            continue
        end = fmt.find("}", index + 1)
        if end < 0:
            return False
        inner = fmt[index + 1:end]
        if inner == "" or inner.isidentifier():
            return True
        index = end + 1
    return False


def _last_nonempty(text: str) -> str:
    for line in reversed((text or "").splitlines()):
        if line.strip():
            return line.strip()
    return ""


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

    def verify_skel(self, skel: Path, contract: Path):
        if self._backend is None:
            return None, self._error or "skelnet not found"
        result = self._backend.verify(skel, contract)
        if not isinstance(result.payload, dict):
            return None, result.error or "skelnet verify produced no JSON"
        return result.payload, None

    def check_skel(self, skel: Path):
        if self._backend is None:
            return None, [], self._error or "skelnet not found"
        result = self._backend.check(skel)
        payload = result.payload if isinstance(result.payload, dict) else {}
        codes = []
        for item in payload.get("diagnostics") or []:
            if isinstance(item, dict) and item.get("code"):
                codes.append(str(item["code"]))
        return result.exit_code, codes, None

    def lower_json(self, skel: Path):
        if self._backend is None:
            return None, self._error or "skelnet not found"
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
            return None, self._error or "concir-backend not found"
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
