"""O4: structural fidelity via instrumentation + the runtime monitor.

``concir-instrument --wrappers`` annotates the program and emits
``resources.json``; the annotated program is built and run K times, each writing
a trace; ``concir-backend monitor`` then checks the task contract against the
observed traces. This module also generates the resource-alignment mapping
(instrumented names carry a ``#site`` suffix and a type counter), counts the
threads actually started from the traces, and derives ``design_loss``.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from pathlib import Path

from .base import FAIL, NOT_RUN, PASS, UNAVAILABLE, UNSUPPORTED, LayerResult
from .runner import ToolRunner

_SITE_RE = re.compile(r"#\d+$")
_TYPE_RE = re.compile(r"_(mutex|condvar|semaphore|sem|channel|rwlock|barrier|once|atomic)\d+$")
# Only these three count for `extra_sync`; channels name their endpoints
# differently, so a name-based rule would misfire.
_SYNC_KINDS = ("Mutex", "Condvar", "Semaphore")
_SAFETY_KINDS = {"safety", "never_holds_all", "unreachable"}
_REACH_KINDS = {"preserved", "reachable", "reachability", "always_reachable"}

# Spawn forms the instrumenter does not rewrite. `cir_trace::spawn(` and
# `__skelnet_serial_spawn(` do not match these patterns.
_RESIDUAL_PATTERNS = [
    (re.compile(r"\bthread\s*::\s*spawn\s*\("), "thread::spawn"),
    (re.compile(r"\.spawn\s*\("), ".spawn("),
    (re.compile(r"\bthread\s*::\s*scope\b"), "thread::scope"),
]


def instrumented_cargo_toml(concir_sync_path: Path | str, *, name: str = "o4_probe") -> str:
    return f"""[package]
name = "{name}"
version = "0.1.0"
edition = "2021"

[[bin]]
name = "{name}"
path = "src/main.rs"

[dependencies]
concir_sync = {{ path = "{concir_sync_path}" }}

[workspace]
"""


def binding_of(resource_name: str) -> str:
    """Strip the ``#site`` suffix and the instrumented type counter."""
    name = _SITE_RE.sub("", resource_name)
    return _TYPE_RE.sub("", name)


def contract_names(contract: dict) -> set[str]:
    out: set[str] = set()

    def walk(value):
        if isinstance(value, dict):
            for key in ("resource", "function"):
                if isinstance(value.get(key), str):
                    out.add(value[key])
            if isinstance(value.get("resources"), list):
                for item in value["resources"]:
                    if isinstance(item, str):
                        out.add(item)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(contract)
    return out


def build_mapping(resource_names: list[str], contract: dict) -> dict[str, str]:
    """Map instrumented resource names to contract FQNs, skipping misses."""
    names = contract_names(contract)
    mapping: dict[str, str] = {}
    for resource in resource_names:
        binding = binding_of(resource)
        target = None
        local = f"main::{binding}"
        if local in names:
            target = local
        elif binding in names:
            target = binding
        else:
            suffix = sorted(n for n in names
                            if n.rsplit("::", 1)[-1] == binding)
            target = suffix[0] if suffix else None
        if target is not None:
            mapping[resource] = target
    return mapping


def reference_thread_count(gold: dict) -> int:
    """Threads the reference design starts: scope targets + spawn nodes."""
    total = 0

    def walk(value):
        nonlocal total
        if isinstance(value, dict):
            if value.get("kind") == "scope" and isinstance(value.get("funcs"), list):
                total += len(value["funcs"])
            if value.get("kind") == "spawn" and value.get("func"):
                total += 1
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(gold)
    return total


def residual_spawns(annotated: str) -> list[str]:
    """Spawn forms left un-rewritten in the annotated program."""
    return [name for pattern, name in _RESIDUAL_PATTERNS if pattern.search(annotated)]


def trace_thread_count(traces_dir: Path | str) -> int:
    """Max worker-thread count observed across the traces.

    Actual threads = max(distinct non-``t0`` tags, ``spawn`` events) per run;
    un-instrumented threads still get a lazy ``t<n>`` tag at their first sync
    operation.
    """
    best = 0
    for path in sorted(Path(traces_dir).glob("*.jsonl")):
        tags: set[str] = set()
        spawns = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            tag = event.get("t") or ""
            if tag and tag != "t0":
                tags.add(tag)
            if event.get("op") == "spawn":
                spawns += 1
        best = max(best, len(tags), spawns)
    return best


def gold_resource_types(gold: dict) -> Counter:
    counts: Counter = Counter()

    def walk(value):
        if isinstance(value, dict):
            if value.get("kind") == "sync" and isinstance(value.get("type"), str):
                counts[value["type"]] += 1
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(gold)
    return counts


def extra_sync_reason(resources: list[dict], gold: dict | None) -> str | None:
    """`extra_sync` when the program builds more Mutex/Condvar/Semaphore sites
    than the reference design declares."""
    if not gold:
        return None
    program: Counter = Counter()
    for resource in resources:
        kind = resource.get("kind")
        if kind in _SYNC_KINDS:
            program[kind] += 1
    reference = gold_resource_types(gold)
    for kind in _SYNC_KINDS:
        have = program.get(kind, 0)
        want = reference.get(kind, 0)
        if have > want:
            sites = [r.get("name", "") for r in resources if r.get("kind") == kind]
            return f"extra_sync: {kind} {have} > {want} ({', '.join(sites)})"
    return None


def _property_categories(report: dict) -> tuple[set[str], str, bool]:
    properties = report.get("properties") or []
    total = len(properties)
    applicable = [p for p in properties if p.get("status") != "unsupported"]
    coverage = f"{len(applicable)}/{total}"
    categories: set[str] = set()
    for prop in properties:
        status = prop.get("status")
        kind = prop.get("kind")
        if kind in _SAFETY_KINDS and status == "FAIL":
            categories.add("monitor_fail")
        elif status == "unmapped":
            categories.add("unmapped")
        elif kind in _REACH_KINDS and status == "not_observed":
            categories.add("not_observed")
    all_unsupported = bool(total) and not applicable
    return categories, coverage, all_unsupported


def classify_o4(report: dict, resources: list[dict], resource_names: list[str],
                mapping: dict[str, str], gold: dict | None, annotated: str,
                traces_dir: Path | str, wall: int | None) -> LayerResult:
    residual = residual_spawns(annotated)
    prop_cats, coverage, all_unsupported = _property_categories(report)
    actual = trace_thread_count(traces_dir)
    reference = reference_thread_count(gold) if gold else None
    thread_loss = reference is not None and actual < reference
    extra = extra_sync_reason(resources, gold)

    categories = set(prop_cats)
    if extra:
        categories.add("design_loss")
    if thread_loss and not residual:
        categories.add("design_loss")
    if residual:
        categories.add("instrument_unsupported")

    detail_parts: list[str] = []
    if extra:
        detail_parts.append(extra)
    if thread_loss and not residual:
        detail_parts.append(f"threads: {actual} < reference {reference}")
    if residual:
        detail_parts.append("residual spawn: " + ", ".join(residual))

    if "monitor_fail" in categories:
        status, category = FAIL, "monitor_fail"
    elif "design_loss" in categories:
        status, category = FAIL, "design_loss"
    elif "instrument_unsupported" in categories:
        status, category = UNSUPPORTED, "instrument_unsupported"
    elif "unmapped" in categories:
        status, category = FAIL, "unmapped"
    elif "not_observed" in categories:
        status, category = FAIL, "not_observed"
    elif all_unsupported:
        status, category = UNSUPPORTED, None
    else:
        status, category = PASS, None

    detail = "; ".join(detail_parts) if detail_parts else f"coverage {coverage}"
    data = {
        "report": report,
        "mapping": mapping,
        "coverage": coverage,
        "categories": sorted(categories),
        "unmapped_program_resources": [n for n in resource_names if n not in mapping],
        "actual_threads": actual,
        "reference_threads": reference,
    }
    return LayerResult("O4", status, category, detail, wall, data)


def evaluate_o4(tools: ToolRunner, workdir: Path | str, src: str, *,
                task_dir: Path | str | None, instrument_bin: str | None = None,
                backend_bin: str | None = None, concir_sync_path: Path | str | None = None,
                runs: int = 5, run_timeout: float = 30.0, timeout: float = 300.0,
                cargo: str = "cargo") -> LayerResult:
    started = time.monotonic()
    task_dir = Path(task_dir).resolve() if task_dir else None
    contract_path = task_dir / "contract.json" if task_dir else None
    gold_path = task_dir / "gold.cir.json" if task_dir else None
    if contract_path is None or not contract_path.exists():
        return LayerResult("O4", NOT_RUN, "no_contract",
                           "no contract.json for this task",
                           int((time.monotonic() - started) * 1000))
    if gold_path is None or not gold_path.exists():
        return LayerResult("O4", NOT_RUN, "no_gold",
                           "no gold.cir.json for this task",
                           int((time.monotonic() - started) * 1000))
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    gold = json.loads(gold_path.read_text(encoding="utf-8"))

    if not instrument_bin or not backend_bin:
        return LayerResult("O4", UNAVAILABLE, "tool_missing",
                           "concir-instrument/concir-backend not configured",
                           int((time.monotonic() - started) * 1000))

    base = Path(workdir) / "o4"
    src_dir = base / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    source_path = src_dir / "main.rs"
    source_path.write_text(src, encoding="utf-8")
    inst_dir = base / "instrumented"
    inst_dir.mkdir(parents=True, exist_ok=True)

    instrument = tools.run(
        [instrument_bin, str(source_path), "--out", str(inst_dir), "--wrappers"],
        base, timeout=timeout)
    if instrument.error is not None:
        return LayerResult("O4", UNAVAILABLE, "tool_missing",
                           f"concir-instrument unavailable: {instrument.error}",
                           int((time.monotonic() - started) * 1000))
    if instrument.returncode != 0:
        return LayerResult("O4", FAIL, "monitor_fail",
                           f"instrument failed: {_first_line(instrument.stderr)}",
                           int((time.monotonic() - started) * 1000))

    annotated = inst_dir / "annotated.rs"
    runtime = inst_dir / "cir_trace.rs"
    resources_path = inst_dir / "resources.json"
    if not annotated.exists() or not resources_path.exists():
        return LayerResult("O4", FAIL, "monitor_fail",
                           "instrument produced no annotated.rs/resources.json",
                           int((time.monotonic() - started) * 1000))
    annotated_text = annotated.read_text(encoding="utf-8")
    resources_doc = json.loads(resources_path.read_text(encoding="utf-8"))
    resources = resources_doc.get("resources") or []
    resource_names = [r.get("name", "") for r in resources if r.get("name")]

    mapping = build_mapping(resource_names, contract)
    mapping_path = base / "mapping.json"
    mapping_path.write_text(json.dumps({"mapping": mapping}, indent=2),
                            encoding="utf-8")

    # Build the annotated project.
    project = base / "project"
    (project / "src").mkdir(parents=True, exist_ok=True)
    (project / "Cargo.toml").write_text(
        instrumented_cargo_toml(concir_sync_path), encoding="utf-8")
    (project / "src" / "main.rs").write_text(annotated_text, encoding="utf-8")
    if runtime.exists():
        (project / "src" / "cir_trace.rs").write_text(runtime.read_text(encoding="utf-8"),
                                                      encoding="utf-8")
    build = tools.run([cargo, "build"], project, timeout=timeout, offline=True)
    if build.error is not None:
        return LayerResult("O4", UNAVAILABLE, "tool_missing",
                           f"cargo unavailable: {build.error}",
                           int((time.monotonic() - started) * 1000))
    if build.returncode != 0 or build.timed_out:
        return LayerResult("O4", FAIL, "monitor_fail",
                           f"instrumented build failed: {_first_line(build.stderr)}",
                           int((time.monotonic() - started) * 1000))
    binary = project / "target" / "debug" / "o4_probe"

    traces_dir = base / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    for index in range(runs):
        trace_path = traces_dir / f"run{index}.jsonl"
        run = tools.run([str(binary)], project, timeout=run_timeout,
                        env_extra={"CIR_TRACE_OUT": str(trace_path)})
        if run.error is not None:
            return LayerResult("O4", FAIL, "monitor_fail",
                               f"instrumented run {index} failed: {run.error}",
                               int((time.monotonic() - started) * 1000))
        if run.timed_out:
            return LayerResult("O4", FAIL, "monitor_fail",
                               f"instrumented run {index} timeout",
                               int((time.monotonic() - started) * 1000))

    monitor = tools.run(
        [backend_bin, "monitor", "--contract", str(contract_path),
         "--resources", str(resources_path), "--traces", str(traces_dir),
         "--mapping", str(mapping_path)],
        base, timeout=timeout)
    wall = int((time.monotonic() - started) * 1000)
    if monitor.error is not None:
        return LayerResult("O4", UNAVAILABLE, "tool_missing",
                           f"concir-backend unavailable: {monitor.error}", wall)
    try:
        report = json.loads(monitor.stdout)
    except json.JSONDecodeError:
        return LayerResult("O4", FAIL, "monitor_fail",
                           f"monitor produced no JSON: {_first_line(monitor.stderr)}",
                           wall)

    return classify_o4(report, resources, resource_names, mapping, gold,
                       annotated_text, traces_dir, wall)


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()[:200]
    return ""
