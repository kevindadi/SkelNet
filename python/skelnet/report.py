"""Round-8 statistics and reporting for run directories.

Reads only ``MANIFEST.json`` / ``cells/**/result.json`` (plus an optional
``--fp-check`` / ``--probe`` JSON and the task ``requirements.json`` files under
``--root``).  Never calls the oracle, a model, or an external tool; never writes
a key; never emits an absolute path into a generated file.  All randomness goes
through :func:`random.Random` instances, so a given input and seed reproduces
byte-identical output.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from . import stats
from .schema import validate_cell

GROUP_ORDER = ["SKEL", "CIR", "G0", "REFINE", "STATIC", "DYNAMIC", "DYNAMIC_M"]
MAIN_BASELINES = ["G0", "REFINE", "STATIC", "DYNAMIC"]
SECONDARY_BASELINES = ["DYNAMIC_M"]
DESIGN_LABELS = ["SKEL", "CIR", "SKEL-outcome"]
EXTRA_LABELS = ["SKEL-nocex", "SKEL-nomap"]

MODEL_ORDER = ["gpt-6-luna", "kimi-k3", "deepseek-flash", "qwen3.8-flash"]
MODEL_HEADER = {"gpt-6-luna": "GPT", "kimi-k3": "Kimi",
                "deepseek-flash": "DeepSeek", "qwen3.8-flash": "Qwen"}
MODEL_FAMILY = {"gpt-6-luna": "GPT", "kimi-k3": "Kimi",
                "deepseek-flash": "DeepSeek", "qwen3.8-flash": "Qwen"}

FAIL_COLUMNS = ["build", "policy", "hang", "output", "deadl", "other",
                "design", "monitor"]
_FAIL_MAP = {
    "O1": {"no_build": "build", "policy_violation": "policy"},
    "O2": {"hang": "hang", "wrong_output": "output", "no_output": "output",
           "crash": "output"},
    "O3": {"deadlock": "deadl", "panic": "other", "thread_leak": "other",
           "ub": "other", "wrong_output": "other", "livelock": "other"},
    "O4": {"design_loss": "design", "monitor_fail": "monitor",
           "not_observed": "monitor", "unmapped": "monitor"},
}


class ReportInputError(Exception):
    """A user-facing report input problem (exit code 2)."""


def group_label(arm: str, feedback_mode: str | None) -> str:
    """D8-4: the analysis label (arm, plus the SKEL ablations)."""
    if arm == "SKEL":
        if feedback_mode == "outcome_only":
            return "SKEL-outcome"
        if feedback_mode == "nocex":
            return "SKEL-nocex"
        if feedback_mode == "nomap":
            return "SKEL-nomap"
    return arm


@dataclass
class Cell:
    raw: dict
    run_id: str
    label: str
    arm: str
    model_id: str
    model_name: str
    task: str
    tier: str | None
    origin: str
    rep: int
    status: str
    ok: bool | None
    sens: bool | None
    accepted: bool
    error: str | None
    final_call: int | None
    billable_tokens: int
    reasoning_tokens: int
    input_tokens: int
    output_tokens: int
    llm_wall_ms: int
    tool_wall_ms: int | None
    oracle_wall_ms: int | None
    fail_column: str | None
    deadlock: bool
    coverage: dict

    @property
    def included(self) -> bool:
        return self.status != "skipped"


def _int_sum(values) -> tuple[int, bool]:
    total = 0
    found = False
    for value in values:
        if isinstance(value, int) and not isinstance(value, bool):
            total += value
            found = True
    return total, found


def _token_totals(cell: dict) -> dict:
    billable = reasoning = input_t = output_t = 0
    for call in cell.get("calls") or []:
        usage = call.get("usage") or {}
        inp = usage.get("input")
        out = usage.get("output")
        reason = usage.get("reasoning")
        if isinstance(inp, int):
            input_t += inp
            billable += inp
        if isinstance(out, int):
            output_t += out
            billable += out
        if isinstance(reason, int):
            reasoning += reason
    return {"billable": billable, "reasoning": reasoning, "input": input_t,
            "output": output_t}


def _llm_wall(cell: dict) -> int:
    total = 0
    for call in cell.get("calls") or []:
        value = call.get("wall_ms")
        if isinstance(value, int) and not isinstance(value, bool):
            total += value
    return total


def _tool_wall(cell: dict) -> int | None:
    values = [cell.get("compile_wall_ms")]
    for item in cell.get("history") or []:
        values.append(item.get("wall_ms"))
    for attempt in cell.get("rust_attempts") or []:
        values.append(attempt.get("compile_wall_ms"))
    baseline = cell.get("baseline") or {}
    for row in baseline.get("rounds") or []:
        values.append(row.get("compile_wall_ms"))
        tools = row.get("tools") or {}
        for tool in tools.values():
            if isinstance(tool, dict):
                values.append(tool.get("wall_ms"))
    total, found = _int_sum(values)
    return total if found else None


def _oracle_wall(cell: dict) -> int | None:
    layers = (cell.get("oracle") or {}).get("layers") or {}
    total, found = _int_sum(layer.get("wall_ms") for layer in layers.values())
    return total if found else None


def _final_call(cell: dict) -> int | None:
    arm = cell.get("arm")
    if cell.get("rust_mode") == "codegen":
        return None
    if arm == "G0":
        return 1 if cell.get("calls") else None
    if arm in ("SKEL", "CIR"):
        attempts = cell.get("rust_attempts") or []
        skeleton_calls = sum(
            1 for call in cell.get("calls") or []
            if call.get("stage") not in ("rust", "rust_fix"))
        index = None
        for i, attempt in enumerate(attempts):
            if attempt.get("reply_kind") == "program":
                index = i
        return skeleton_calls + (index + 1) if index is not None else None
    last = None
    for row in (cell.get("baseline") or {}).get("rounds") or []:
        if row.get("reply_kind") == "program":
            value = row.get("call")
            if isinstance(value, int):
                last = value
    return last


def _fail_column(cell: dict) -> str | None:
    oracle = cell.get("oracle") or {}
    if oracle.get("functional_ok") is not False:
        return None
    layers = oracle.get("layers") or {}
    for name in ("O1", "O2", "O3", "O4"):
        layer = layers.get(name)
        if isinstance(layer, dict) and layer.get("status") == "fail":
            category = layer.get("category")
            mapped = _FAIL_MAP.get(name, {}).get(category)
            if mapped:
                return mapped
            if name == "O3":
                # An unknown O3 category stays in the O3 "other" column (and
                # is reported by _unclassified_warnings).
                return "other"
            return None
    return None


def _unclassified_warnings(cells) -> list[str]:
    tally: dict = {}
    for cell in cells:
        if not cell.included:
            continue
        oracle = cell.raw.get("oracle") or {}
        if oracle.get("functional_ok") is not False:
            continue
        layers = oracle.get("layers") or {}
        for name in ("O1", "O2", "O3", "O4"):
            layer = layers.get(name)
            if not (isinstance(layer, dict) and layer.get("status") == "fail"):
                continue
            category = layer.get("category")
            if _FAIL_MAP.get(name, {}).get(category):
                break
            key = f"{name}:{category}"
            tally[key] = tally.get(key, 0) + 1
            break
    return [f"unclassified failing layer {key} in {count} cell(s)"
            for key, count in sorted(tally.items())]


def _deadlock(cell: dict) -> bool:
    layers = (cell.get("oracle") or {}).get("layers") or {}
    o2 = layers.get("O2") or {}
    o3 = layers.get("O3") or {}
    return (o2.get("category") == "hang" or o3.get("category") == "deadlock")


def _compile_unavailable(cell: dict) -> bool:
    if cell.get("error") in ("compile_unavailable", "compile_timeout"):
        return True
    for attempt in cell.get("rust_attempts") or []:
        if attempt.get("compile") in ("unavailable", "timeout"):
            return True
    for row in (cell.get("baseline") or {}).get("rounds") or []:
        if row.get("compile") in ("unavailable", "timeout"):
            return True
    return False


def _coverage(cell: dict) -> dict:
    oracle = cell.get("oracle") or {}
    layers = oracle.get("layers") or {}
    o3 = layers.get("O3") or {}
    o4 = layers.get("O4") or {}
    o3_tools = oracle.get("o3_tools")
    detail = (o3.get("detail") or "").lower()
    shuttle = miri = None
    if isinstance(o3_tools, dict):
        shuttle = (o3_tools.get("shuttle") or {}).get("status")
        miri = (o3_tools.get("miri") or {}).get("status")
    shuttle_unsupported = shuttle == "unsupported" or (
        shuttle is None and "shuttle" in detail and "unsupported" in detail)
    miri_unsupported = miri == "unsupported" or (
        miri is None and "miri" in detail and "unsupported" in detail)
    no_concurrency = (bool(o3_tools.get("no_concurrency"))
                      if isinstance(o3_tools, dict)
                      else "no concurrency to explore" in detail)
    return {
        "instrument_unsupported": o4.get("category") == "instrument_unsupported",
        "shuttle_unsupported": bool(shuttle_unsupported),
        "miri_unsupported": bool(miri_unsupported),
        "no_concurrency": bool(no_concurrency),
        "compile_unavailable": _compile_unavailable(cell),
        "oracle_complete_false": oracle.get("oracle_complete") is False,
        "functional_null": oracle.get("functional_ok") is None,
    }


def _read_origin(root: Path, task: str) -> str:
    path = root / "benchmarks" / "tasks" / task / "requirements.json"
    if not path.exists():
        return "unknown"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    origin = data.get("origin")
    return origin if origin in ("classic", "disguised") else "unknown"


@dataclass
class Dataset:
    cells: list[Cell]
    run_ids: list[str]
    git_sha: str
    warnings: list[str] = field(default_factory=list)
    mixed: list[str] = field(default_factory=list)
    n_skipped: int = 0
    n_error: int = 0
    statuses: list[str] = field(default_factory=list)
    manifests: list[dict] = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    null_reasons: dict = field(default_factory=dict)

    def included(self, label=None, model=None, task=None) -> list[Cell]:
        out = []
        for cell in self.cells:
            if not cell.included:
                continue
            if label is not None and cell.label != label:
                continue
            if model is not None and cell.model_id != model:
                continue
            if task is not None and cell.task != task:
                continue
            out.append(cell)
        return out

    def labels(self) -> list[str]:
        seen = []
        for cell in self.cells:
            if cell.label not in seen:
                seen.append(cell.label)
        return seen

    def models(self) -> list[str]:
        seen = []
        for cell in self.cells:
            if cell.model_id not in seen:
                seen.append(cell.model_id)
        ordered = [m for m in MODEL_ORDER if m in seen]
        ordered += [m for m in seen if m not in MODEL_ORDER]
        return ordered

    def rate(self, label, predicate, **filters) -> float | None:
        cells = self.included(label, **filters)
        if not cells:
            return None
        return sum(1 for c in cells if predicate(c)) / len(cells)

    def pairs(self, label_a, label_b) -> dict[str, list[tuple[bool, bool]]]:
        index_a = {(c.model_id, c.task, c.rep): c for c in self.included(label_a)}
        index_b = {(c.model_id, c.task, c.rep): c for c in self.included(label_b)}
        out: dict[str, list[tuple[bool, bool]]] = {}
        for key in sorted(set(index_a) & set(index_b)):
            model_dot = key[0]
            out.setdefault(model_dot, []).append(
                (index_a[key].ok is True, index_b[key].ok is True))
        return out

    def pair_units(self, label_a, label_b):
        index_a = {(c.model_id, c.task, c.rep): c for c in self.included(label_a)}
        index_b = {(c.model_id, c.task, c.rep): c for c in self.included(label_b)}
        units = []
        for key in sorted(set(index_a) & set(index_b)):
            a = index_a[key].ok is True
            b = index_b[key].ok is True
            units.append((key[1], int(a) - int(b)))
        return units


def load_runs(run_dirs, *, root=".", allow_duplicates: bool = False,
              allow_mixed: bool = False) -> Dataset:
    return _assemble(run_dirs, Path(root), allow_duplicates, allow_mixed)


def _consistency_check(manifests, run_ids, *, allow_mixed):
    warnings: list[str] = []
    mixed: list[str] = []
    checks = [("hint", lambda m: m.get("hint"))]
    for key in ("call_budget", "token_budget", "temperature_policy",
                "seed_policy"):
        checks.append((key, lambda m, k=key: (m.get("run_params") or {}).get(k)))
    for name, getter in checks:
        values = {getter(m) for m in manifests}
        if len(values) > 1:
            message = f"{name} differs across runs: {sorted(map(str, values))}"
            if allow_mixed:
                mixed.append(message)
            else:
                raise ReportInputError(message)
    per_model: dict = {}
    for manifest in manifests:
        model_id = manifest.get("model_id")
        value = (manifest.get("run_params") or {}).get("max_output_tokens")
        per_model.setdefault(model_id, set()).add(value)
    for model_id, values in per_model.items():
        if len(values) > 1:
            message = f"max_output_tokens differs for {model_id}: {sorted(map(str, values))}"
            if allow_mixed:
                mixed.append(message)
            else:
                raise ReportInputError(message)
    return warnings, mixed


def _assemble(run_dirs, root, allow_duplicates, allow_mixed) -> Dataset:
    all_cells: list[Cell] = []
    seen: dict = {}
    run_ids: list[str] = []
    manifests: list[dict] = []
    warnings: list[str] = []
    statuses: list[str] = []
    n_skipped = n_error = 0
    skipped_dupes: list[str] = []
    for run_dir in run_dirs:
        run_dir = Path(run_dir)
        manifest_path = run_dir / "MANIFEST.json"
        if not manifest_path.exists():
            raise ReportInputError(
                f"{run_dir.name} is not a run directory (no MANIFEST.json)")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        run_id = manifest.get("run_id") or run_dir.name
        run_ids.append(run_id)
        manifests.append(manifest)
        selected = (manifest.get("tasks") or {}).get("selected") or []
        reps = manifest.get("reps")
        if not isinstance(reps, int):
            reps = 0
        run_params = manifest.get("run_params") or {}
        feedback_mode = run_params.get("feedback_mode")
        for task in selected:
            for rep in range(reps):
                path = run_dir / "cells" / task / str(rep) / "result.json"
                if not path.exists():
                    continue
                raw = json.loads(path.read_text(encoding="utf-8"))
                errors = validate_cell(raw)
                if errors:
                    raise ReportInputError(
                        f"invalid cell in run {run_id}: {task}/{rep}: {errors}")
                label = group_label(raw.get("arm"), feedback_mode)
                key = (raw.get("model_id"), label, raw.get("task"), rep)
                if key in seen:
                    if not allow_duplicates:
                        raise ReportInputError(
                            f"duplicate cell {key} (use --allow-duplicates)")
                    skipped_dupes.append(str(key))
                seen[key] = (raw, run_id, label, root)
    for (raw, run_id, label, root_path) in seen.values():
        status = raw.get("status")
        if status == "skipped":
            n_skipped += 1
        if status == "error":
            n_error += 1
        all_cells.append(_make_cell(raw, run_id, label, root_path))
    if skipped_dupes:
        warnings.append("duplicate cells kept the last: " + ", ".join(
            sorted(set(skipped_dupes))))
    statuses = [m.get("status") if isinstance(m.get("status"), str) else "unknown"
                for m in manifests]
    for run_id, status in zip(run_ids, statuses):
        if status not in (None, "complete"):
            warnings.append(f"run {run_id} has status {status!r}")
    consistency_warnings, mixed = _consistency_check(
        manifests, run_ids, allow_mixed=allow_mixed)
    warnings.extend(consistency_warnings)
    warnings.extend(_unavailable_warnings(all_cells))
    warnings.extend(_unclassified_warnings(all_cells))
    git_shas = {m.get("git_sha") for m in manifests if m.get("git_sha")}
    git_sha = (git_shas.pop() if len(git_shas) == 1 else "mixed") if git_shas else "unknown"
    counts = _group_counts(all_cells)
    null_reasons = _null_reason_counts(all_cells)
    return Dataset(cells=all_cells, run_ids=run_ids, git_sha=git_sha,
                   warnings=warnings, mixed=mixed, n_skipped=n_skipped,
                   n_error=n_error, statuses=statuses, manifests=manifests,
                   counts=counts, null_reasons=null_reasons)


def _group_counts(cells) -> dict:
    """Per label: included / skipped / error (D8-1, D8-2)."""
    counts: dict = {}
    for cell in cells:
        entry = counts.setdefault(cell.label, {"included": 0, "skipped": 0,
                                               "error": 0})
        if cell.status == "skipped":
            entry["skipped"] += 1
        else:
            entry["included"] += 1
            if cell.status == "error":
                entry["error"] += 1
    return counts


def _null_reason(cell) -> str | None:
    oracle = cell.raw.get("oracle")
    if not isinstance(oracle, dict) or not oracle:
        return "no_oracle"
    layers = oracle.get("layers") or {}
    for name in ("O1", "O2", "O3", "O4"):
        if (layers.get(name) or {}).get("status") == "unavailable":
            return f"unavailable:{name}"
    if oracle.get("terminal_check") == "not_applicable":
        return "not_applicable"
    if oracle.get("functional_ok") is None:
        return "other"
    return None


def _null_reason_counts(cells) -> dict:
    counts: dict = {}
    for cell in cells:
        if not cell.included:
            continue
        reason = _null_reason(cell)
        if reason is None:
            continue
        entry = counts.setdefault(cell.label, {})
        entry[reason] = entry.get(reason, 0) + 1
    return counts


def _unavailable_warnings(cells) -> list[str]:
    """D8-1: warn once per layer/group that has unavailable layers."""
    tally: dict = {}
    for cell in cells:
        if not cell.included:
            continue
        layers = (cell.raw.get("oracle") or {}).get("layers") or {}
        for name in ("O1", "O2", "O3", "O4"):
            if (layers.get(name) or {}).get("status") == "unavailable":
                tally[(name, cell.label)] = tally.get((name, cell.label), 0) + 1
    warnings = []
    for (name, label), count in sorted(tally.items()):
        warnings.append(
            f"unavailable layer {name} in {count} {label} cell(s)")
    return warnings


def _make_cell(raw: dict, run_id: str, label: str, root: Path) -> Cell:
    oracle = raw.get("oracle") or {}
    tokens = _token_totals(raw)
    tier = raw.get("tier")
    return Cell(
        raw=raw, run_id=run_id, label=label, arm=raw.get("arm", "?"),
        model_id=raw.get("model_id") or "?",
        model_name=raw.get("model") or raw.get("model_id") or "?",
        task=raw.get("task", "?"), tier=tier if isinstance(tier, str) else None,
        origin=_read_origin(root, raw.get("task", "?")),
        rep=raw.get("rep", 0), status=raw.get("status", "ok"),
        ok=oracle.get("functional_ok") is True,
        sens=oracle.get("functional_ok_no_o4") is True,
        accepted=bool(raw.get("accepted")),
        error=raw.get("error"),
        final_call=_final_call(raw),
        billable_tokens=tokens["billable"], reasoning_tokens=tokens["reasoning"],
        input_tokens=tokens["input"], output_tokens=tokens["output"],
        llm_wall_ms=_llm_wall(raw), tool_wall_ms=_tool_wall(raw),
        oracle_wall_ms=_oracle_wall(raw), fail_column=_fail_column(raw),
        deadlock=_deadlock(raw), coverage=_coverage(raw))


# ── formatting (D8-13) ───────────────────────────────────────────────────

def _pct(v) -> str:
    return "--" if v is None else f"{v * 100:.1f}"


def _signed(v, minus: str = "$-$") -> str:
    rounded = round(v, 1)
    if rounded == 0:
        rounded = 0.0
    text = f"{abs(rounded):.1f}"
    return f"+{text}" if rounded >= 0 else minus + text


def _pp(v) -> str:
    return "--" if v is None else _signed(v)


def _ci(lo, hi) -> str:
    if lo is None or hi is None:
        return "--"
    return f"[{_signed(lo)}, {_signed(hi)}]"


def _pp_md(v) -> str:
    return "--" if v is None else _signed(v, minus="\u2212")


def _ci_md(lo, hi) -> str:
    if lo is None or hi is None:
        return "--"
    return f"[{_signed(lo, minus='\u2212')}, {_signed(hi, minus='\u2212')}]"


def _pval(p) -> str:
    if p is None:
        return "--"
    if p < 0.001:
        return "<0.001"
    if p <= 0:
        return "0.000"
    exponent = math.floor(math.log10(p))
    decimals = max(0, 2 - exponent)
    return f"{p:.{decimals}f}"


def _num(v, digits: int = 3) -> str:
    return "--" if v is None else f"{v:.{digits}g}"


def _thousands(v) -> str:
    return "--" if v is None else f"{v / 1000.0:.1f}"


def _seconds(ms) -> str:
    return "--" if ms is None else f"{ms / 1000.0:.1f}"


def _calls(v) -> str:
    return "--" if v is None else f"{v:.2f}"


def _tex_label(label: str) -> str:
    return "\\arm{" + label.replace("_", "\\_") + "}"


def _gen_comment(name: str, ds: Dataset) -> str:
    runs = ", ".join(ds.run_ids) if ds.run_ids else "(none)"
    return (f"% Generated by python -m skelnet report ({name}) from runs: "
            f"{runs}; git {ds.git_sha[:12]}; do not edit.")


@dataclass
class ReportContext:
    root: Path
    look: int = 0
    planned_units: int = 880
    previous_look_units: int = 528
    bootstrap: int = 10000
    seed: int = 20260928
    prices: dict | None = None
    fp_check: dict | None = None
    probe: dict | None = None
    call_budget: int = 5
    allow_duplicates: bool = False
    allow_mixed: bool = False


def _main_paired_units(ds: Dataset) -> int:
    sets = []
    for label in ["SKEL"] + MAIN_BASELINES:
        sets.append({(c.model_id, c.task, c.rep) for c in ds.included(label)})
    common = sets[0]
    for other in sets[1:]:
        common = common & other
    return len(common)


def nominal_alpha(ds: Dataset, ctx: ReportContext):
    """The sequential nominal alpha at this look, or None (look 0/1)."""
    if ctx.look not in (2, 3):
        return None
    units = _main_paired_units(ds)
    if units == 0:
        return None
    t = units / ctx.planned_units
    t = min(max(t, 1e-6), 1.0)
    if ctx.look == 2:
        return stats.obf_nominal_boundaries([t, 1.0])[0]
    t2 = min(max(ctx.previous_look_units / ctx.planned_units, 1e-6), 1.0)
    return stats.obf_nominal_boundaries([t2, 1.0])[1]


def _comparison(ds: Dataset, reference: str, control: str,
                ctx: ReportContext) -> dict:
    pairs_by_model = ds.pairs(reference, control)
    merged = stats.stratified_mcnemar(pairs_by_model)
    units = ds.pair_units(reference, control)
    boot = stats.cluster_bootstrap_diff(units, n_boot=ctx.bootstrap,
                                        seed=ctx.seed)
    index_a = {(c.model_id, c.task, c.rep) for c in ds.included(reference)}
    index_b = {(c.model_id, c.task, c.rep) for c in ds.included(control)}
    if not units:
        delta = ci_low = ci_high = None
    else:
        delta = boot["point"] * 100.0
        ci_low = boot["ci_low"] * 100.0
        ci_high = boot["ci_high"] * 100.0
    return {
        "reference": reference, "control": control,
        "b": merged["b"], "c": merged["c"], "p": merged["p"],
        "per_model": merged["per_model"],
        "delta": delta, "ci_low": ci_low, "ci_high": ci_high,
        "n_units": len(units),
        "missing_reference": len(index_a - index_b),
        "missing_control": len(index_b - index_a),
        "per_model_delta": {
            model: (sum(int(a) - int(b) for a, b in pairs) / len(pairs) * 100.0
                    if pairs else None)
            for model, pairs in pairs_by_model.items()},
    }


def _pass3(ds: Dataset, label: str, *, sens: bool = False) -> dict:
    result: dict = {}
    for model in ds.models():
        for task in sorted({c.task for c in ds.cells}):
            cells = ds.included(label, model=model, task=task)
            n = len(cells)
            if n == 0:
                continue
            correct = sum(1 for c in cells if (c.sens if sens else c.ok))
            result[(model, task)] = stats.pass_at_k(n, correct, min(3, n))
    return result


def _pass3_means(table: dict, models) -> dict:
    per_model = {}
    for model in models:
        values = [v for (m, _), v in table.items() if m == model]
        per_model[model] = sum(values) / len(values) if values else None
    pooled = list(table.values())
    return {"per_model": per_model,
            "pooled": sum(pooled) / len(pooled) if pooled else None}


def table_main(ds: Dataset, ctx: ReportContext) -> dict:
    models = list(MODEL_ORDER)
    rows = []
    family1 = []
    family2 = []
    comparisons: dict = {}
    for label in ["G0", "REFINE", "STATIC", "DYNAMIC"]:
        comparisons[label] = _comparison(ds, "SKEL", label, ctx)
        family1.append(comparisons[label]["p"])
    comparisons["CIR"] = _comparison(ds, "SKEL", "CIR", ctx)
    for label in ["G0", "REFINE", "STATIC", "DYNAMIC"]:
        comparisons[f"CIR:{label}"] = _comparison(ds, "CIR", label, ctx)
    comparisons["DYNAMIC_M"] = _comparison(ds, "SKEL", "DYNAMIC_M", ctx)
    family2 = [comparisons[f"CIR:{label}"]["p"] for label in
               ["G0", "REFINE", "STATIC", "DYNAMIC"]]
    family2 += [comparisons["CIR"]["p"], comparisons["DYNAMIC_M"]["p"]]
    holm1 = stats.holm(family1)
    holm2 = stats.holm(family2)
    p_holm = {}
    for index, label in enumerate(["G0", "REFINE", "STATIC", "DYNAMIC"]):
        p_holm[label] = holm1[index]
    for index, key in enumerate(["CIR:G0", "CIR:REFINE", "CIR:STATIC",
                                 "CIR:DYNAMIC", "CIR", "DYNAMIC_M"]):
        p_holm[key] = holm2[index]

    for label in GROUP_ORDER:
        row = {
            "label": label,
            "per_model": {m: ds.rate(label, lambda c: c.ok, model=m)
                          for m in models},
            "pooled": ds.rate(label, lambda c: c.ok),
            "sens": ds.rate(label, lambda c: c.sens),
        }
        if ctx.look == 0:
            row.update({"delta": None, "ci_low": None, "ci_high": None,
                        "p": None, "family": None})
        elif label == "SKEL":
            row.update({"delta": None, "ci_low": None, "ci_high": None,
                        "p": None, "family": None})
        else:
            comparison = comparisons[label]
            row.update({"delta": comparison["delta"],
                        "ci_low": comparison["ci_low"],
                        "ci_high": comparison["ci_high"],
                        "p": p_holm[label],
                        "family": ("main" if label in MAIN_BASELINES
                                   else "secondary")})
        rows.append(row)

    pass3 = _pass3(ds, "G0")
    pass3_sens = _pass3(ds, "G0", sens=True)
    means = _pass3_means(pass3, models)
    means_sens = _pass3_means(pass3_sens, models)
    pass3_short = {}
    for model in models:
        for task in sorted({c.task for c in ds.cells}):
            n = len(ds.included("G0", model=model, task=task))
            if 0 < n < 3:
                pass3_short[f"{model}/{task}"] = n
    skel_p1 = ds.rate("SKEL", lambda c: c.ok)
    units = []
    p1_by = {}
    for model in ds.models():
        for task in sorted({c.task for c in ds.cells}):
            cells = ds.included("SKEL", model=model, task=task)
            if not cells:
                continue
            p1_by[(model, task)] = sum(1 for c in cells if c.ok) / len(cells)
    for key, value in pass3.items():
        if key in p1_by:
            units.append((key[1], p1_by[key] - value))
    if ctx.look == 0 or skel_p1 is None or means["pooled"] is None:
        pass3_row = {"label": "G0 pass@3", "per_model": means["per_model"],
                     "pooled": means["pooled"], "sens": means_sens["pooled"],
                     "delta": None, "ci_low": None, "ci_high": None, "p": None,
                     "family": None}
    else:
        boot = stats.cluster_bootstrap_diff(units, n_boot=ctx.bootstrap,
                                            seed=ctx.seed)
        pass3_row = {"label": "G0 pass@3", "per_model": means["per_model"],
                     "pooled": means["pooled"], "sens": means_sens["pooled"],
                     "delta": boot["point"] * 100.0,
                     "ci_low": boot["ci_low"] * 100.0,
                     "ci_high": boot["ci_high"] * 100.0, "p": None,
                     "family": None}

    cochran = _cochran_by_model(ds)
    alpha = nominal_alpha(ds, ctx)
    return {"models": models, "rows": rows, "pass3": pass3_row,
            "cochran": cochran, "alpha": alpha, "look": ctx.look,
            "comparisons": comparisons, "holm": p_holm,
            "pass3_short": pass3_short}


def _cochran_by_model(ds: Dataset) -> dict:
    groups = ["SKEL", "CIR", "G0", "REFINE", "STATIC", "DYNAMIC"]
    out = {}
    for model in ds.models():
        index = {}
        for label in groups:
            for cell in ds.included(label, model=model):
                index.setdefault((cell.task, cell.rep), {})[label] = cell
        blocks = []
        for key, row in index.items():
            if all(label in row for label in groups):
                blocks.append([1 if row[label].ok else 0 for label in groups])
        if blocks:
            result = stats.cochran_q(blocks)
            out[model] = {"Q": result["Q"], "p": result["p"],
                          "df": result["df"], "n": len(blocks)}
        else:
            out[model] = None
    return out


def table_tiers(ds: Dataset, ctx: ReportContext) -> dict:
    rows = []
    for label in GROUP_ORDER:
        cells = ds.included(label)
        def rate_for(pred):
            subset = [c for c in cells if pred(c)]
            return sum(1 for c in subset if c.ok) / len(subset) if subset else None
        rows.append({
            "label": label,
            "L1": rate_for(lambda c: c.tier == "L1"),
            "L2": rate_for(lambda c: c.tier == "L2"),
            "L3": rate_for(lambda c: c.tier == "L3"),
            "unclassified": rate_for(lambda c: c.tier is None),
            "classic": rate_for(lambda c: c.origin == "classic"),
            "disguised": rate_for(lambda c: c.origin == "disguised"),
        })
    return {"rows": rows}


def _check_at_1(cell: Cell) -> bool:
    history = cell.raw.get("history") or []
    first = next((h for h in history if h.get("attempt") == 1), None)
    if first is None:
        return False
    if first.get("stage") == "verify":
        if cell.arm == "CIR":
            return first.get("outcome") not in ("INVALID", "UNSUPPORTED")
        return True
    if first.get("stage") == "check":
        status = first.get("status")
        return status in ("ok", "pass", "semantic")
    return False


def _verified_at_1(cell: Cell) -> bool:
    history = cell.raw.get("history") or []
    first = next((h for h in history if h.get("attempt") == 1), None)
    if first is None or first.get("stage") != "verify":
        return False
    return first.get("outcome") == "PASS" and first.get("complete") is True


def _unmapped_values(cell: Cell):
    values = []
    for item in cell.raw.get("history") or []:
        if item.get("stage") != "verify":
            continue
        unmapped = item.get("unmapped")
        if isinstance(unmapped, list):
            values.append(len(unmapped))
        elif isinstance(unmapped, int) and not isinstance(unmapped, bool):
            values.append(unmapped)
    return values


def table_design(ds: Dataset, ctx: ReportContext) -> dict:
    rows = []
    for label in DESIGN_LABELS:
        cells = ds.included(label)
        if not cells:
            rows.append({"label": label, "parse": None, "check": None,
                         "verified1": None, "verified4": None, "unknown": None,
                         "unmapped": None, "verified_not_ok": None, "n": 0})
            continue
        def rate(pred):
            return sum(1 for c in cells if pred(c)) / len(cells)
        unmapped = None
        if label != "CIR":
            values = [v for c in cells for v in _unmapped_values(c)]
            unmapped = sum(values) / len(values) if values else None
        rows.append({
            "label": label,
            "parse": rate(lambda c: bool(c.raw.get("parse_ok"))),
            "check": rate(_check_at_1),
            "verified1": rate(_verified_at_1),
            "verified4": rate(lambda c: c.raw.get("skel_verified") is True),
            "unknown": rate(lambda c: c.raw.get("skel_status") == "UNKNOWN"),
            "unmapped": unmapped,
            "verified_not_ok": rate(
                lambda c: c.raw.get("skel_verified") is True and not c.ok),
            "n": len(cells),
        })
    return {"rows": rows}


def table_failures(ds: Dataset, ctx: ReportContext) -> dict:
    rows = []
    for label in GROUP_ORDER:
        cells = ds.included(label)
        row = {"label": label, "n": len(cells), "columns": {}}
        for column in FAIL_COLUMNS:
            count = sum(1 for c in cells if c.fail_column == column)
            row["columns"][column] = count / len(cells) if cells else None
        row["deadlock"] = (sum(1 for c in cells if c.deadlock) / len(cells)
                           if cells else None)
        row["false_acc"] = (sum(1 for c in cells if c.accepted and not c.ok)
                            / len(cells) if cells else None)
        rows.append(row)
    return {"rows": rows, "columns": FAIL_COLUMNS}


def _cost_row(label: str, cells: list) -> dict:
    n = len(cells)
    ok_count = sum(1 for c in cells if c.ok)
    billable = sum(c.billable_tokens for c in cells)
    tool_cells = [c for c in cells if c.tool_wall_ms is not None]
    oracle_cells = [c for c in cells if c.oracle_wall_ms is not None]
    first_ok = [c.final_call for c in cells if c.ok and c.final_call]
    cache_calls = [call for c in cells for call in (c.raw.get("calls") or [])
                   if call.get("cache_hit")]
    cache_billable = 0
    for call in cache_calls:
        usage = call.get("usage") or {}
        for key in ("input", "output"):
            value = usage.get(key)
            if isinstance(value, int):
                cache_billable += value
    cache_llm = sum(call.get("wall_ms") or 0 for call in cache_calls)
    return {
        "label": label, "n": n,
        "calls": sum(c.raw.get("budget_used", {}).get("calls", 0)
                     for c in cells) / n,
        "input": sum(c.input_tokens for c in cells) / n,
        "output": sum(c.output_tokens for c in cells) / n,
        "reasoning": sum(c.reasoning_tokens for c in cells) / n,
        "tokens_correct": (billable / ok_count) if ok_count else None,
        "llm_ms": sum(c.llm_wall_ms for c in cells) / n,
        "tool_ms": (sum(c.tool_wall_ms for c in tool_cells) / len(tool_cells)
                    if tool_cells else None),
        "tool_n": len(tool_cells),
        "oracle_ms": (sum(c.oracle_wall_ms for c in oracle_cells)
                      / len(oracle_cells) if oracle_cells else None),
        "first_ok_calls": (sum(first_ok) / len(first_ok) if first_ok
                           else None),
        "cache_hit_calls": len(cache_calls),
        "cache_hit_billable": cache_billable,
        "cache_hit_llm_ms": cache_llm,
    }


def table_cost(ds: Dataset, ctx: ReportContext) -> dict:
    rows = []
    per_model = []
    for label in GROUP_ORDER:
        cells = ds.included(label)
        if not cells:
            rows.append({"label": label, "n": 0})
        else:
            rows.append(_cost_row(label, cells))
        for model in ds.models():
            model_cells = ds.included(label, model=model)
            if model_cells:
                entry = _cost_row(label, model_cells)
                entry["model"] = model
                per_model.append(entry)
    prices = _cost_prices(ds, ctx)
    for model in prices.get("missing", []):
        message = f"missing prices for {model}"
        if message not in ds.warnings:
            ds.warnings.append(message)
    return {"rows": rows, "per_model": per_model, "prices": prices,
            "models": ds.models()}


def _cost_prices(ds: Dataset, ctx: ReportContext) -> dict:
    if not ctx.prices:
        return {}
    per_million = ctx.prices.get("per_million", {})
    currency = ctx.prices.get("currency", "USD")
    by_model = {}
    missing = set()
    for label in GROUP_ORDER:
        for model in ds.models():
            cells = ds.included(label, model=model)
            if not cells:
                continue
            price = per_million.get(model)
            if not price:
                missing.add(model)
                by_model.setdefault(label, {})[model] = None
                continue
            total = 0.0
            for cell in cells:
                cached = sum((call.get("usage") or {}).get("cached") or 0
                             for call in (cell.raw.get("calls") or []))
                uncached = max(0, cell.input_tokens - cached)
                total += (uncached * price.get("input", 0)
                          + cached * price.get("cached_input", price.get("input", 0))
                          + cell.output_tokens * price.get("output", 0)) / 1e6
            by_model.setdefault(label, {})[model] = total
    totals = {}
    for label, entry in by_model.items():
        if all(value is not None for value in entry.values()):
            totals[label] = sum(entry.values())
        else:
            totals[label] = None
    return {"currency": currency, "by_model": by_model, "totals": totals,
            "missing": sorted(missing)}


def table_models(ds: Dataset, ctx: ReportContext) -> dict:
    models = list(MODEL_ORDER)
    rows = []
    for model_id in models:
        policy = None
        for manifest in ds.manifests:
            if manifest.get("model_id") == model_id:
                policy = manifest.get("model_policy") or {}
                break
        calls = [call for cell in ds.cells if cell.model_id == model_id
                 for call in (cell.raw.get("calls") or [])]
        if calls:
            truncated = sum(1 for call in calls
                            if call.get("truncation_retry")
                            or "length" in (call.get("finish_reasons") or []))
            truncation = truncated / len(calls)
        else:
            truncation = None
        seed = None
        if ctx.probe:
            for entry in ctx.probe.get("models", []):
                if entry.get("model_id") == model_id:
                    seed = entry.get("seed_deterministic")
        rows.append({
            "model_id": model_id,
            "family": MODEL_FAMILY.get(model_id, policy.get("display_name")
                                       if policy else model_id),
            "policy": policy,
            "api": _api_label(policy),
            "reasoning": _reasoning_label(policy),
            "truncation": truncation,
            "seed": seed,
        })
    return {"rows": rows}


def _api_label(policy) -> str:
    if not policy:
        return "--"
    if policy.get("surface") == "responses":
        return "Responses (gateway)"
    channel = policy.get("channel") or ""
    if channel.endswith("-direct"):
        return "Chat (direct)"
    return "Chat (gateway)"


def _reasoning_label(policy) -> str:
    if not policy:
        return "--"
    effort = policy.get("reasoning_effort")
    if effort:
        return f"effort \\texttt{{{effort}}}"
    if policy.get("thinking"):
        return "thinking enabled"
    return "--"


def table_benchmark(ds: Dataset, ctx: ReportContext) -> dict:
    families = ["lock-order", "condvar", "semaphore", "channel", "atomic-data",
                "structure"]
    base = ctx.root / "benchmarks" / "tasks"
    counts = {family: {"L1": 0, "L2": 0, "L3": 0} for family in families}
    boundary = 0
    if base.is_dir():
        for path in base.glob("*/*/requirements.json"):
            family = path.parent.parent.name
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            tier = data.get("tier")
            if family == "boundary":
                boundary += 1
            elif family in counts and tier in ("L1", "L2", "L3"):
                counts[family][tier] += 1
    l2_data = sum(counts[f]["L2"] for f in families)
    l3_data = sum(counts[f]["L3"] for f in families)
    has_l2 = l2_data > 0
    has_l3 = l3_data > 0
    rows = []
    for family in families:
        row = {"family": family, "L1": counts[family]["L1"],
               "L2": counts[family]["L2"] if has_l2 else None,
               "L3": counts[family]["L3"] if has_l3 else None}
        rows.append(row)
    l1_total = sum(counts[f]["L1"] for f in families)
    l2_total = l2_data if has_l2 else 12
    l3_total = l3_data if has_l3 else 8
    return {"rows": rows, "boundary": boundary,
            "source": ("data" if (has_l2 or has_l3) else "D10"),
            "total": {"L1": l1_total, "L2": l2_total, "L3": l3_total,
                      "Total": l1_total + l2_total + l3_total}}


def table_coverage(ds: Dataset, ctx: ReportContext) -> dict:
    keys = ["instrument_unsupported", "shuttle_unsupported", "miri_unsupported",
            "no_concurrency", "compile_unavailable", "oracle_complete_false",
            "functional_null"]
    rows = []
    for label in GROUP_ORDER + ["SKEL-outcome"] + EXTRA_LABELS:
        cells = ds.included(label)
        if not cells:
            continue
        row = {"label": label, "n": len(cells)}
        for key in keys:
            row[key] = sum(1 for c in cells if c.coverage.get(key)) / len(cells)
        rows.append(row)
    per_model = []
    for label in GROUP_ORDER:
        for model in ds.models():
            cells = ds.included(label, model=model)
            if not cells:
                continue
            row = {"label": label, "model": model, "n": len(cells)}
            for key in keys:
                row[key] = (sum(1 for c in cells if c.coverage.get(key))
                            / len(cells))
            per_model.append(row)
    reasons = sorted({reason for entry in ds.null_reasons.values()
                      for reason in entry})
    return {"keys": keys, "rows": rows, "per_model": per_model,
            "reasons": reasons, "null_reasons": ds.null_reasons}


def _lockbud_ratios(bucket: dict) -> dict:
    dead = bucket["tp"] + bucket["fn"]
    ok = bucket["ok_fail"] + bucket["ok_pass"]
    not_dead = bucket["fp"] + bucket["tn"]
    return {
        "recall": bucket["tp"] / dead if dead else None,
        "fp_on_ok": bucket["ok_fail"] / ok if ok else None,
        "report_on_not_deadlock": bucket["fp"] / not_dead if not_dead else None,
    }


def _empty_bucket() -> dict:
    return {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "ok_fail": 0, "ok_pass": 0}


def table_lockbud(ds: Dataset, ctx: ReportContext) -> dict:
    reference = ctx.fp_check
    joined = dict(_empty_bucket())
    joined.update({"unavailable": 0, "excluded": 0, "no_g0": 0})
    per_model: dict = {}
    per_family: dict = {}
    g0_index = {(c.model_id, c.task, c.rep): c for c in ds.included("G0")}
    for cell in ds.included("STATIC"):
        rounds = (cell.raw.get("baseline") or {}).get("rounds") or []
        first = next((r for r in rounds if r.get("version") == 1
                      and r.get("compiled") is True), None)
        if first is None:
            joined["excluded"] += 1
            continue
        lockbud = (first.get("tools") or {}).get("lockbud") or {}
        status = lockbud.get("status")
        if status == "unavailable":
            joined["unavailable"] += 1
            continue
        counterpart = g0_index.get((cell.model_id, cell.task, cell.rep))
        if counterpart is None or counterpart.raw.get("oracle") is None:
            joined["no_g0"] += 1
            continue
        dead = counterpart.deadlock
        ok = counterpart.ok is True
        reported = status == "fail"
        bucket = ("tp" if reported and dead else "fp" if reported
                  else "fn" if dead else "tn")
        joined[bucket] += 1
        if ok:
            joined["ok_fail" if reported else "ok_pass"] += 1
        for store, key in ((per_model, cell.model_id),
                           (per_family, cell.task.split("/")[0])):
            entry = store.setdefault(key, _empty_bucket())
            entry[bucket] += 1
            if ok:
                entry["ok_fail" if reported else "ok_pass"] += 1
    for store in (per_model, per_family):
        for entry in store.values():
            entry.update(_lockbud_ratios(entry))
    return {"reference": reference, "joined": joined,
            "ratios": _lockbud_ratios(joined),
            "per_model": per_model, "per_family": per_family,
            "reference_by_family": _fp_check_by_family(reference)}


def _fp_check_by_family(reference: dict | None) -> dict:
    if not reference:
        return {}
    families: dict = {}
    for task in reference.get("tasks", []):
        family = task.get("task", "").split("/")[0]
        entry = families.setdefault(family, {
            "clippy": {"fixed_hits": 0, "fixed_n": 0, "buggy_hits": 0,
                       "buggy_n": 0},
            "lockbud": {"fixed_hits": 0, "fixed_n": 0, "buggy_hits": 0,
                        "buggy_n": 0}})
        for program in task.get("programs", []):
            role = program.get("role")
            for tool in ("clippy", "lockbud"):
                column = program.get(tool) or {}
                if column.get("status") != "ok":
                    continue
                key = "findings" if tool == "clippy" else "records"
                hit = bool(column.get(key))
                bucket = "fixed" if role == "fixed" else "buggy"
                entry[tool][f"{bucket}_n"] += 1
                if hit:
                    entry[tool][f"{bucket}_hits"] += 1
    return families


def _wilcoxon_pairs(ds: Dataset, reference: str, control: str, metric):
    """Per (model, task) means, then paired Wilcoxon over the two groups."""
    index: dict = {}
    for label in (reference, control):
        for cell in ds.included(label):
            index.setdefault((label, cell.model_id, cell.task), []).append(cell)
    diffs = []
    xs = []
    ys = []
    for model in ds.models():
        for task in sorted({c.task for c in ds.cells}):
            a = index.get((reference, model, task))
            b = index.get((control, model, task))
            if not a or not b:
                continue
            av = sum(metric(c) for c in a) / len(a)
            bv = sum(metric(c) for c in b) / len(b)
            diffs.append(av - bv)
            xs.append(av)
            ys.append(bv)
    if not diffs:
        return None
    test = stats.wilcoxon_signed_rank(diffs)
    return {"p": test["p"], "method": test["method"], "n": test["n"],
            "a12": stats.a12(xs, ys) if xs and ys else None,
            "cliffs": stats.cliffs_delta(xs, ys) if xs and ys else None}


def _subset_comparison(ds, reference, control, predicate, ctx) -> dict:
    """Paired stats on the units where ``predicate(reference_cell)`` holds."""
    index_a = {(c.model_id, c.task, c.rep): c for c in ds.included(reference)
               if predicate(c)}
    index_b = {(c.model_id, c.task, c.rep): c for c in ds.included(control)}
    units = []
    b = c = 0
    for key in sorted(set(index_a) & set(index_b)):
        a_ok = index_a[key].ok is True
        b_ok = index_b[key].ok is True
        units.append((key[1], int(a_ok) - int(b_ok)))
        if a_ok and not b_ok:
            b += 1
        elif b_ok and not a_ok:
            c += 1
    if not units:
        return {"b": 0, "c": 0, "n": 0, "delta": None, "ci_low": None,
                "ci_high": None}
    boot = stats.cluster_bootstrap_diff(units, n_boot=ctx.bootstrap,
                                        seed=ctx.seed)
    return {"b": b, "c": c, "n": len(units),
            "delta": boot["point"] * 100.0, "ci_low": boot["ci_low"] * 100.0,
            "ci_high": boot["ci_high"] * 100.0}


def table_tests(ds: Dataset, ctx: ReportContext) -> dict:
    comparisons = []
    for control in MAIN_BASELINES:
        comparisons.append(("main", "SKEL", control))
    for control in MAIN_BASELINES:
        comparisons.append(("secondary", "CIR", control))
    comparisons.append(("secondary", "SKEL", "CIR"))
    comparisons.append(("secondary", "SKEL", "DYNAMIC_M"))
    family1 = [c for c in comparisons if c[0] == "main"]
    family2 = [c for c in comparisons if c[0] == "secondary"]
    p1 = [stats.stratified_mcnemar(ds.pairs(r, c))["p"] for _, r, c in family1]
    p2 = [stats.stratified_mcnemar(ds.pairs(r, c))["p"] for _, r, c in family2]
    holm1 = stats.holm(p1)
    holm2 = stats.holm(p2)
    rows = []
    for index, (family, reference, control) in enumerate(comparisons):
        comparison = _comparison(ds, reference, control, ctx)
        adjusted = (holm1 if family == "main" else holm2)[
            0 if family == "main" else index - len(family1)]
        comparison["family"] = family
        comparison["p_holm"] = adjusted
        comparison["key"] = f"{reference}-{control}"
        comparison["per_model_stats"] = {}
        for model in ds.models():
            entry = _subset_comparison(
                ds, reference, control, lambda c, m=model: c.model_id == m, ctx)
            comparison["per_model_stats"][model] = entry
        comparison["per_tier_stats"] = {}
        for tier in ("L1", "L2", "L3", "unclassified"):
            if tier == "unclassified":
                pred = lambda c: c.tier is None
            else:
                pred = lambda c, t=tier: c.tier == t
            comparison["per_tier_stats"][tier] = _subset_comparison(
                ds, reference, control, pred, ctx)
        rows.append(comparison)
    dynamic_m_q = _cochran_seven(ds)
    metrics = {}
    for family, reference, control in comparisons:
        metrics[f"{reference}-{control}"] = {
            "tokens": _wilcoxon_pairs(
                ds, reference, control, lambda c: c.billable_tokens),
            "calls": _wilcoxon_pairs(
                ds, reference, control,
                lambda c: c.raw.get("budget_used", {}).get("calls", 0)),
        }
    return {"rows": rows, "family1": holm1, "family2": holm2,
            "dynamic_m_q": dynamic_m_q, "metrics": metrics}


def _cochran_seven(ds: Dataset) -> dict:
    groups6 = ["SKEL", "CIR", "G0", "REFINE", "STATIC", "DYNAMIC"]
    groups7 = groups6 + ["DYNAMIC_M"]
    out = {}
    for model in ds.models():
        index: dict = {}
        for label in groups7:
            for cell in ds.included(label, model=model):
                index.setdefault((cell.task, cell.rep), {})[label] = cell
        blocks6 = [row for row in index.values()
                   if all(label in row for label in groups6)]
        covered = [row for row in blocks6 if "DYNAMIC_M" in row]
        if blocks6 and len(covered) == len(blocks6):
            blocks = [[1 if row[label].ok else 0 for label in groups7]
                      for row in covered]
            result = stats.cochran_q(blocks)
            out[model] = {"Q": result["Q"], "df": result["df"],
                          "p": result["p"], "blocks": len(blocks),
                          "covered": len(covered), "total": len(blocks6)}
        else:
            out[model] = {"Q": None, "df": None, "p": None,
                          "blocks": len(covered), "covered": len(covered),
                          "total": len(blocks6)}
    return out


def table_numbers(ds: Dataset, ctx: ReportContext) -> dict:
    cells = [c for c in ds.cells if c.included]
    calls = [call for c in cells for call in (c.raw.get("calls") or [])]
    truncated = sum(1 for call in calls if call.get("truncation_retry")
                    or "length" in (call.get("finish_reasons") or []))
    lockbud_fp = None
    if ctx.fp_check:
        lockbud_fp = (ctx.fp_check.get("summary", {}).get("lockbud", {})
                      .get("fixed_fp_rate"))
    return {
        "units": _main_paired_units(ds),
        "calls": len(calls),
        "tokens": sum(c.billable_tokens for c in cells),
        "truncation": truncated / len(calls) if calls else None,
        "incomplete": (sum(1 for c in cells if c.coverage["oracle_complete_false"])
                       / len(cells) if cells else None),
        "shuttle_unsupported": (sum(
            1 for c in cells if c.coverage["shuttle_unsupported"]) / len(cells)
            if cells else None),
        "instrument_unsupported": (sum(
            1 for c in cells if c.coverage["instrument_unsupported"]) / len(cells)
            if cells else None),
        "lockbud_fp": lockbud_fp,
        "look": ctx.look,
        "alpha": nominal_alpha(ds, ctx),
    }


def anytime_data(ds: Dataset, ctx: ReportContext) -> dict:
    labels = GROUP_ORDER + ["SKEL-outcome"]
    series = []
    total_excluded = 0
    for label in labels:
        all_cells = ds.included(label)
        cells = [c for c in all_cells if c.raw.get("rust_mode") != "codegen"]
        if not all_cells:
            continue
        excluded = len(all_cells) - len(cells)
        total_excluded += excluded
        if not cells:
            continue
        points = []
        for b in range(1, ctx.call_budget + 1):
            hit = sum(1 for c in cells
                      if c.ok and c.final_call is not None
                      and c.final_call <= b)
            points.append({"b": b, "ok_rate": hit / len(cells),
                           "n": len(cells)})
        series.append({"label": label, "points": points,
                       "excluded_codegen": excluded})
    return {"series": series, "call_budget": ctx.call_budget,
            "excluded_codegen": total_excluded}


# ── LaTeX renderers (layout matches the paper placeholders) ─────────────

def render_main_tex(payload: dict, ds: Dataset, ctx: ReportContext) -> str:
    lines = [
        _gen_comment("main", ds),
        "% RQ1/RQ2 main table. Filled by report.py (round 8) from Stage-2 (or Stage-3) runs.",
        "\\begin{tabular}{@{}lrrrrr|rrr|r@{}}",
        "\\toprule",
        "& \\multicolumn{5}{c|}{\\textbf{pass@1 of $\\mathit{ok}$ (\\%)}} & \\multicolumn{3}{c|}{\\textbf{\\arm{SKEL} $-$ arm (pooled)}} & \\textbf{Sens.} \\\\",
        "\\textbf{Arm} & GPT & Kimi & DeepSeek & Qwen & Pooled & $\\Delta$ (pp) & 95\\% CI & $p_{\\text{Holm}}$ & O1--O3 \\\\",
        "\\midrule",
    ]

    def row_str(row):
        cells = [_pct(row["per_model"].get(model)) for model in payload["models"]]
        cells.append(_pct(row.get("pooled")))
        if row.get("delta") is None:
            cells += ["--", "--", "--"]
        else:
            p = _pval(row.get("p"))
            if row.get("family") == "secondary":
                p += "$^{s}$"
            cells += [_pp(row["delta"]), _ci(row["ci_low"], row["ci_high"]), p]
        cells.append(_pct(row.get("sens")))
        label = row["label"]
        if label == "G0 pass@3":
            text = "\\arm{G0} pass@3"
        else:
            text = _tex_label(label)
        return text + " & " + " & ".join(cells) + " \\\\"

    for row in payload["rows"]:
        lines.append(row_str(row))
        if row["label"] == "CIR":
            lines.append("\\midrule")
    lines.append("\\midrule")
    lines.append(row_str(payload["pass3"]))
    lines.append("\\bottomrule")
    cochran = []
    for model in payload["models"]:
        header = MODEL_HEADER.get(model, model)
        value = payload["cochran"].get(model)
        if value:
            cochran.append(f"{header} $Q$={_num(value['Q'])} "
                           f"($p$={_pval(value['p'])})")
        else:
            cochran.append(f"{header} $Q$=--")
    if payload.get("look") == 0:
        alpha = "-- (Stage 0: descriptive only)"
    elif payload["alpha"] is None:
        alpha = "--"
    else:
        alpha = _num(payload["alpha"])
    lines.append(
        "\\multicolumn{10}{@{}l@{}}{\\scriptsize $^{s}$ secondary family. "
        "Cochran's Q per model: " + "; ".join(cochran) +
        ". Sequential boundary at this look: $\\alpha=$" + alpha + ".}")
    lines.append("\\end{tabular}")
    return "\n".join(lines) + "\n"


def render_tiers_tex(payload, ds, ctx) -> str:
    lines = [
        _gen_comment("tiers", ds),
        "% RQ1 by tier and task origin, pooled over models (pass@1 of ok, %).",
        "\\begin{tabular}{@{}lrrrrr@{}}",
        "\\toprule",
        "\\textbf{Arm} & \\textbf{L1} & \\textbf{L2} & \\textbf{L3} & "
        "\\textbf{classic} & \\textbf{disguised} \\\\",
        "\\midrule",
    ]
    for row in payload["rows"]:
        cells = [_pct(row[key]) for key in
                 ("L1", "L2", "L3", "classic", "disguised")]
        lines.append(_tex_label(row["label"]) + " & " + " & ".join(cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}"]
    return "\n".join(lines) + "\n"


def render_design_tex(payload, ds, ctx) -> str:
    lines = [
        _gen_comment("design", ds),
        "% RQ3: design-stage metrics for the three design arms (pooled; SKEL-outcome is DeepSeek only).",
        "\\begin{tabular}{@{}lrrrrrrr@{}}",
        "\\toprule",
        "\\textbf{Arm} & \\textbf{parse@1} & \\textbf{check@1} & "
        "\\textbf{verified@1} & \\textbf{verified@4} & \\textbf{UNKNOWN} & "
        "\\textbf{unmapped} & \\textbf{verified $\\wedge\\neg\\mathit{ok}$} \\\\",
        "\\midrule",
    ]
    for row in payload["rows"]:
        unmapped = "n/a" if row["label"] == "CIR" else _num(row["unmapped"])
        cells = [_pct(row["parse"]), _pct(row["check"]), _pct(row["verified1"]),
                 _pct(row["verified4"]), _pct(row["unknown"]), unmapped,
                 _pct(row["verified_not_ok"])]
        lines.append(_tex_label(row["label"]) + " & " + " & ".join(cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}"]
    return "\n".join(lines) + "\n"


def render_failures_tex(payload, ds, ctx) -> str:
    lines = [
        _gen_comment("failures", ds),
        "% RQ4: first failing oracle layer / category of final programs (% of cells, pooled).",
        "\\begin{tabular}{@{}lrrrrrrrr|rr@{}}",
        "\\toprule",
        "& \\multicolumn{2}{c}{\\textbf{O1}} & \\multicolumn{2}{c}{\\textbf{O2}} & "
        "\\multicolumn{2}{c}{\\textbf{O3}} & \\multicolumn{2}{c|}{\\textbf{O4}} & & \\\\",
        "\\textbf{Arm} & build & policy & hang & output & deadl. & other & design & "
        "monitor & \\textbf{deadlock rate} & \\textbf{false acc.} \\\\",
        "\\midrule",
    ]
    for row in payload["rows"]:
        cells = [_pct(row["columns"][column]) for column in FAIL_COLUMNS]
        cells += [_pct(row["deadlock"]), _pct(row["false_acc"])]
        lines.append(_tex_label(row["label"]) + " & " + " & ".join(cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}"]
    return "\n".join(lines) + "\n"


def render_cost_tex(payload, ds, ctx) -> str:
    lines = [
        _gen_comment("cost", ds),
        "% RQ5: cost per cell (mean) and per correct program, pooled over models.",
        "\\begin{tabular}{@{}lrrrrrrr@{}}",
        "\\toprule",
        "\\textbf{Arm} & \\textbf{calls} & \\textbf{input k} & "
        "\\textbf{output k} & \\textbf{reasoning k} & "
        "\\textbf{tokens/correct k} & \\textbf{LLM s} & \\textbf{tool s} \\\\",
        "\\midrule",
    ]
    for row in payload["rows"]:
        if not row.get("n"):
            cells = ["--"] * 7
        else:
            cells = [_calls(row["calls"]), _thousands(row["input"]),
                     _thousands(row["output"]), _thousands(row["reasoning"]),
                     _thousands(row["tokens_correct"]),
                     _seconds(row["llm_ms"]), _seconds(row["tool_ms"])]
        lines.append(_tex_label(row["label"]) + " & " + " & ".join(cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}"]
    return "\n".join(lines) + "\n"


def render_models_tex(payload, ds, ctx) -> str:
    lines = [
        _gen_comment("models", ds),
        "% Models (experiment-plan §2.2, decisions K2--K4, D3, D5). Effective values are",
        "% recorded per run in MANIFEST.json; the probe column is filled after Stage 0.",
        "\\begin{tabular}{@{}llllp{0.22\\linewidth}@{}}",
        "\\toprule",
        "\\textbf{Family} & \\textbf{Model id} & \\textbf{API} & "
        "\\textbf{Reasoning} & \\textbf{Stage-0 probe (truncation, seed honoured)} \\\\",
        "\\midrule",
    ]
    for row in payload["rows"]:
        probe = "--"
        if row["truncation"] is not None:
            seed = {True: "yes", False: "no", None: "--"}.get(row["seed"], "--")
            probe = f"trunc {_pct(row['truncation'])}\\%; seed {seed}"
        lines.append(
            f"{row['family']} & \\texttt{{{row['model_id']}}} & {row['api']} & "
            f"{row['reasoning']} & {probe} \\\\")
    lines += ["\\bottomrule", "\\end{tabular}"]
    return "\n".join(lines) + "\n"


def render_benchmark_tex(payload, ds, ctx) -> str:
    lines = [
        _gen_comment("benchmark", ds),
        "% Benchmark composition (experiment-plan §4, D10). L1 counts are the current",
        "% benchmarks/tasks/ families; L2/L3 counts are fixed by D10 (12 + 8) but the",
        "% per-family split is decided in round 7b.",
        "\\begin{tabular}{@{}lrrrr@{}}",
        "\\toprule",
        "\\textbf{Family} & \\textbf{L1} & \\textbf{L2} & \\textbf{L3} & "
        "\\textbf{Total} \\\\",
        "\\midrule",
    ]
    for row in payload["rows"]:
        l2 = "--" if row["L2"] is None else str(row["L2"])
        l3 = "--" if row["L3"] is None else str(row["L3"])
        total = row["L1"] + (row["L2"] or 0) + (row["L3"] or 0)
        total_text = str(total) if (row["L2"] is not None
                                    and row["L3"] is not None) else "--"
        lines.append(f"{row['family']} & {row['L1']} & {l2} & {l3} & {total_text} \\\\")
    total = payload["total"]
    lines.append("\\midrule")
    lines.append(f"\\textbf{{Total}} & \\textbf{{{total['L1']}}} & "
                 f"\\textbf{{{total['L2']}}} & \\textbf{{{total['L3']}}} & "
                 f"\\textbf{{{total['Total']}}} \\\\")
    lines.append("\\addlinespace")
    lines.append(
        "\\multicolumn{5}{@{}p{0.9\\linewidth}@{}}{\\scriptsize Tier criteria: "
        "L1 $\\le$3 threads, $\\le$2 resources, one mechanism, $\\le$300 states; "
        "L2 3--4 threads, two mechanisms, 300--5k states; L3 4--6 threads, "
        "$\\ge$3 mechanisms or a parameterised protocol, 5k--100k states (gold "
        "skeleton must still \\textsf{PASS} completely). Boundary negatives ("
        + str(payload["boundary"]) + ") are reported separately.}\\\\")
    lines += ["\\bottomrule", "\\end{tabular}"]
    return "\n".join(lines) + "\n"


def render_coverage_tex(payload, ds, ctx) -> str:
    keys = payload["keys"]
    header = " & ".join("\\textbf{" + key.replace("_", "\\_") + "}"
                        for key in keys)
    lines = [_gen_comment("coverage", ds),
             "\\begin{tabular}{@{}lr" + "r" * len(keys) + "@{}}",
             "\\toprule",
             "\\textbf{Arm} & \\textbf{n} & " + header + " \\\\",
             "\\midrule"]
    for row in payload["rows"]:
        cells = [_pct(row[key]) for key in keys]
        lines.append(_tex_label(row["label"]) + f" & {row['n']} & "
                     + " & ".join(cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}"]
    return "\n".join(lines) + "\n"


def render_lockbud_tex(payload, ds, ctx) -> str:
    joined = payload["joined"]
    ratios = payload["ratios"]
    lines = [_gen_comment("lockbud", ds),
             "% (a) reference programs by family",
             "\\begin{tabular}{@{}llrrrr@{}}",
             "\\toprule",
             "\\textbf{Family} & \\textbf{Tool} & \\textbf{fixed FP} & "
             "\\textbf{fixed n} & \\textbf{buggy hits} & \\textbf{buggy n} \\\\",
             "\\midrule"]
    for family, entry in sorted(payload.get("reference_by_family", {}).items()):
        for tool in ("clippy", "lockbud"):
            row = entry[tool]
            lines.append(f"{family} & {tool} & {row['fixed_hits']} & "
                         f"{row['fixed_n']} & {row['buggy_hits']} & "
                         f"{row['buggy_n']} \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", "",
              "% (b) experiment 2x2",
              "\\begin{tabular}{@{}lrrrr@{}}",
              "\\toprule",
              "\\textbf{Group} & \\textbf{tp} & \\textbf{fp} & \\textbf{fn} & "
              "\\textbf{tn} \\\\",
              "\\midrule"]
    lines.append(f"pooled & {joined['tp']} & {joined['fp']} & {joined['fn']} & "
                 f"{joined['tn']} \\\\")
    for model, entry in sorted(payload["per_model"].items()):
        lines.append(f"{model} & {entry['tp']} & {entry['fp']} & {entry['fn']} & "
                     f"{entry['tn']} \\\\")
    for family, entry in sorted(payload["per_family"].items()):
        lines.append(f"{family} & {entry['tp']} & {entry['fp']} & {entry['fn']} & "
                     f"{entry['tn']} \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", "",
              f"% recall {_num(ratios['recall'])}, "
              f"FP on oracle-ok {_num(ratios['fp_on_ok'])}, "
              f"report on not-deadlock {_num(ratios['report_on_not_deadlock'])}, "
              f"no_g0 {joined['no_g0']}, unavailable {joined['unavailable']}, "
              f"excluded (no v1 compile) {joined['excluded']}"]
    return "\n".join(lines) + "\n"


def render_tests_tex(payload, ds, ctx) -> str:
    lines = [_gen_comment("tests", ds),
             "\\begin{tabular}{@{}llrrrrrrrr@{}}",
             "\\toprule",
             "\\textbf{Family} & \\textbf{Comparison} & \\textbf{b} & \\textbf{c} & "
             "\\textbf{p} & \\textbf{$p_{Holm}$} & \\textbf{$\\Delta$ (pp)} & "
             "\\textbf{95\\% CI} & \\textbf{n} & \\textbf{missing} \\\\",
             "\\midrule"]
    for row in payload["rows"]:
        missing = (f"{row['missing_reference']}/{row['missing_control']}"
                   if (row["missing_reference"] or row["missing_control"]) else "--")
        lines.append(
            f"{row['family']} & {_tex_label(row['reference'])} $-$ "
            f"{_tex_label(row['control'])} & {row['b']} & {row['c']} & "
            f"{_pval(row['p'])} & {_pval(row['p_holm'])} & "
            f"{_pp(row['delta'])} & {_ci(row['ci_low'], row['ci_high'])} & "
            f"{row['n_units']} & {missing} \\\\")
    lines += ["\\bottomrule", "\\end{tabular}"]
    return "\n".join(lines) + "\n"


def render_numbers_tex(payload, ds, ctx) -> str:
    alpha = "--" if payload["alpha"] is None else _num(payload["alpha"])
    lines = [_gen_comment("numbers", ds),
             "\\newcommand{\\SNunits}{" + str(payload["units"]) + "}",
             "\\newcommand{\\SNcalls}{" + str(payload["calls"]) + "}",
             "\\newcommand{\\SNtokens}{" + f"{payload['tokens']:,}" + "}",
             "\\newcommand{\\SNtruncpct}{" + _pct(payload["truncation"]) + "}",
             "\\newcommand{\\SNincompletepct}{" + _pct(payload["incomplete"]) + "}",
             "\\newcommand{\\SNshuttleunsup}{" + _pct(payload["shuttle_unsupported"]) + "}",
             "\\newcommand{\\SNinstrunsup}{" + _pct(payload["instrument_unsupported"]) + "}",
             "\\newcommand{\\SNlockbudfp}{" + _num(payload["lockbud_fp"]) + "}",
             "\\newcommand{\\SNlook}{" + str(payload["look"]) + "}",
             "\\newcommand{\\SNalpha}{" + alpha + "}"]
    return "\n".join(lines) + "\n"


ANYTIME_COLORS = [("SKEL", "CPVBlue"), ("CIR", "CPVTeal"), ("G0", "gray"),
                  ("REFINE", "gray!70"), ("STATIC", "gray!50"),
                  ("DYNAMIC", "CPVWarn"), ("DYNAMIC_M", "CPVWarn!60")]


def render_anytime_tex(payload: dict, ds: Dataset, ctx: ReportContext) -> str:
    series = {entry["label"]: entry["points"] for entry in payload["series"]}
    lines = [
        _gen_comment("anytime", ds),
        ("% Anytime curve (cumulative ok-rate after b = 1.."
         + str(payload["call_budget"]) + " calls, one line per arm)."),
        "\\begin{tikzpicture}[font=\\sffamily\\scriptsize, x=12mm, y=24mm]",
        "  \\draw[->] (0.6,0) -- (5.5,0) node[below left] {LLM calls spent $b$};",
        "  \\draw[->] (0.6,0) -- (0.6,1.1) node[above right] {cumulative $\\mathit{ok}$ rate};",
        "  \\foreach \\b in {1,...,5} \\draw (\\b,0) -- (\\b,-0.03) node[below] {\\b};",
        "  \\foreach \\y/\\l in {0/0,0.5/50\\%,1/100\\%} \\draw (0.6,\\y) -- (0.55,\\y) node[left] {\\l};",
    ]
    for label, color in ANYTIME_COLORS:
        points = series.get(label)
        if not points:
            continue
        coordinates = " ".join(f"({p['b']},{p['ok_rate']:.4f})" for p in points)
        name = label.replace("_", "\\_")
        lines.append(f"  \\draw[{color}, thick] plot coordinates {{{coordinates}}} "
                     f"node[right] {{{name}}};")
    lines.append("\\end{tikzpicture}")
    return "\n".join(lines) + "\n"


def render_anytime_csv(payload: dict) -> str:
    lines = ["label,b,ok_rate,n"]
    for entry in payload["series"]:
        for point in entry["points"]:
            lines.append(f"{entry['label']},{point['b']},{point['ok_rate']:.6f},"
                         f"{point['n']}")
    return "\n".join(lines) + "\n"


# ── Markdown renderers ──────────────────────────────────────────────────

def render_main_md(payload, ds, ctx) -> str:
    lines = ["| Arm | GPT | Kimi | DeepSeek | Qwen | Pooled | Δ (pp) | 95% CI | p_Holm | Sens. |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in payload["rows"] + [payload["pass3"]]:
        cells = [_pct(row["per_model"].get(m)) for m in payload["models"]]
        cells.append(_pct(row.get("pooled")))
        cells += [_pp_md(row.get("delta")),
                  _ci_md(row.get("ci_low"), row.get("ci_high")),
                  _pval(row.get("p"))]
        cells.append(_pct(row.get("sens")))
        lines.append("| " + row["label"] + " | " + " | ".join(cells) + " |")
    cochran = "; ".join(
        f"{MODEL_HEADER.get(m, m)} Q={_num(v['Q'])} (p={_pval(v['p'])})"
        if (v := payload["cochran"].get(m)) else f"{MODEL_HEADER.get(m, m)} Q=--"
        for m in payload["models"])
    lines.append("")
    if payload.get("look") == 0:
        alpha = "-- (Stage 0: descriptive only)"
    else:
        alpha = _num(payload["alpha"])
    lines.append(f"Cochran's Q per model: {cochran}. "
                 f"Nominal alpha: {alpha}.")
    if payload.get("pass3_short"):
        cells = ", ".join(f"{key} (n={n})"
                          for key, n in sorted(payload["pass3_short"].items()))
        lines.append("")
        lines.append(f"G0 pass@3 uses pass@n for n<3: {cells}.")
    return "\n".join(lines) + "\n"


def render_tiers_md(payload, ds, ctx) -> str:
    lines = ["| Arm | L1 | L2 | L3 | unclassified | classic | disguised |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in payload["rows"]:
        lines.append("| " + row["label"] + " | " + " | ".join(
            _pct(row[k]) for k in ("L1", "L2", "L3", "unclassified",
                                   "classic", "disguised")) + " |")
    return "\n".join(lines) + "\n"


def render_design_md(payload, ds, ctx) -> str:
    lines = ["| Arm | parse@1 | check@1 | verified@1 | verified@4 | UNKNOWN | unmapped | verified∧¬ok |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in payload["rows"]:
        unmapped = "n/a" if row["label"] == "CIR" else _num(row["unmapped"])
        lines.append("| " + row["label"] + " | " + " | ".join([
            _pct(row["parse"]), _pct(row["check"]), _pct(row["verified1"]),
            _pct(row["verified4"]), _pct(row["unknown"]), unmapped,
            _pct(row["verified_not_ok"])]) + " |")
    return "\n".join(lines) + "\n"


def render_failures_md(payload, ds, ctx) -> str:
    lines = ["| Arm | " + " | ".join(FAIL_COLUMNS) +
             " | deadlock rate | false acc. | no failing layer |",
             "| --- | " + " | ".join(["---"] * (len(FAIL_COLUMNS) + 3)) + " |"]
    for row in payload["rows"]:
        columns = [_pct(row["columns"][c]) for c in FAIL_COLUMNS]
        failed = sum(1 for c in FAIL_COLUMNS if row["columns"][c])
        other = 1.0 - (sum(row["columns"][c] or 0 for c in FAIL_COLUMNS)
                       + (ds.rate(row["label"], lambda c: c.ok) or 0))
        lines.append("| " + row["label"] + " | " + " | ".join(
            columns + [_pct(row["deadlock"]), _pct(row["false_acc"]),
                       _pct(other) if row["n"] else "--"]) + " |")
    return "\n".join(lines) + "\n"


_COST_HEADER = ("| Arm | calls | input k | output k | reasoning k | "
                "tokens/correct k | LLM s | tool s | oracle s | first-ok calls |")
_COST_RULE = "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"


def _cost_row_md(label: str, row: dict) -> str:
    if not row.get("n"):
        return "| " + label + " | " + " | ".join(["--"] * 9) + " |"
    return "| " + label + " | " + " | ".join([
        _calls(row["calls"]), _thousands(row["input"]),
        _thousands(row["output"]), _thousands(row["reasoning"]),
        _thousands(row["tokens_correct"]), _seconds(row["llm_ms"]),
        _seconds(row["tool_ms"]), _seconds(row["oracle_ms"]),
        _calls(row["first_ok_calls"])]) + " |"


def render_cost_md(payload, ds, ctx) -> str:
    lines = [_COST_HEADER, _COST_RULE]
    for row in payload["rows"]:
        lines.append(_cost_row_md(row["label"], row))
    lines.append("")
    lines.append("Costs are per cell (mean); `tokens/correct` is total billable "
                 "tokens over correct programs. Costs are computed by running "
                 "each group on its own; a cache-hit first round is billed to "
                 "the group that replays it (D8-12). Tool seconds cover "
                 f"{sum(r.get('tool_n', 0) for r in payload['rows'])} cells.")
    lines.append("")
    lines.append("Per group × model:")
    lines.append("")
    lines.append("| Arm | Model | " + _COST_HEADER.split("|", 2)[2].strip())
    lines.append("| --- | --- | " + " | ".join(["---"] * 9) + " |")
    for row in payload["per_model"]:
        cells = [_calls(row["calls"]), _thousands(row["input"]),
                 _thousands(row["output"]), _thousands(row["reasoning"]),
                 _thousands(row["tokens_correct"]), _seconds(row["llm_ms"]),
                 _seconds(row["tool_ms"]), _seconds(row["oracle_ms"]),
                 _calls(row["first_ok_calls"])]
        lines.append(f"| {row['label']} | {row['model']} | " +
                     " | ".join(cells) + " |")
    lines.append("")
    lines.append("Cache-hit calls (the paired design's saving):")
    lines.append("")
    lines.append("| Arm | cache-hit calls | billable tokens | LLM s |")
    lines.append("| --- | --- | --- | --- |")
    for row in payload["rows"]:
        if not row.get("n"):
            continue
        lines.append(f"| {row['label']} | {row['cache_hit_calls']} | "
                     f"{row['cache_hit_billable']} | "
                     f"{_seconds(row['cache_hit_llm_ms'])} |")
    prices = payload.get("prices") or {}
    if prices:
        lines.append("")
        lines.append(f"Cost in {prices['currency']} (per group × model):")
        lines.append("")
        models = payload.get("models") or []
        lines.append("| Arm | " + " | ".join(models) + " | total |")
        lines.append("| --- | " + " | ".join(["---"] * (len(models) + 1)) + " |")
        for label in GROUP_ORDER:
            entry = prices["by_model"].get(label)
            if not entry:
                continue
            cells = [("--" if entry.get(m) is None else f"{entry[m]:.2f}")
                     for m in models]
            total = prices["totals"].get(label)
            lines.append("| " + label + " | " + " | ".join(cells) + " | " +
                         ("--" if total is None else f"{total:.2f}") + " |")
        if prices["missing"]:
            lines.append("")
            lines.append("> warning: missing prices for " +
                         ", ".join(prices["missing"]))
    return "\n".join(lines) + "\n"


def render_models_md(payload, ds, ctx) -> str:
    lines = ["| Family | Model id | API | Reasoning | truncation | seed |",
             "| --- | --- | --- | --- | --- | --- |"]
    for row in payload["rows"]:
        seed = {True: "yes", False: "no", None: "--"}.get(row["seed"], "--")
        lines.append(f"| {row['family']} | {row['model_id']} | {row['api']} | "
                     f"{row['reasoning']} | {_pct(row['truncation'])} | {seed} |")
    return "\n".join(lines) + "\n"


def render_benchmark_md(payload, ds, ctx) -> str:
    lines = ["| Family | L1 | L2 | L3 | Total |", "| --- | --- | --- | --- | --- |"]
    for row in payload["rows"]:
        l2 = "--" if row["L2"] is None else row["L2"]
        l3 = "--" if row["L3"] is None else row["L3"]
        lines.append(f"| {row['family']} | {row['L1']} | {l2} | {l3} | -- |")
    total = payload["total"]
    lines.append(f"| **Total** | **{total['L1']}** | **{total['L2']}** | "
                 f"**{total['L3']}** | **{total['Total']}** |")
    lines.append("")
    lines.append(f"Boundary negatives: {payload['boundary']}.")
    return "\n".join(lines) + "\n"


def render_coverage_md(payload, ds, ctx) -> str:
    keys = payload["keys"]
    lines = ["| Arm | n | " + " | ".join(keys) + " |",
             "| --- | --- | " + " | ".join(["---"] * len(keys)) + " |"]
    for row in payload["rows"]:
        lines.append("| " + row["label"] + f" | {row['n']} | " +
                     " | ".join(_pct(row[key]) for key in keys) + " |")
    lines.append("")
    lines.append("Per group × model:")
    lines.append("")
    lines.append("| Arm | Model | n | " + " | ".join(keys) + " |")
    lines.append("| --- | --- | --- | " + " | ".join(["---"] * len(keys)) + " |")
    for row in payload["per_model"]:
        lines.append("| " + row["label"] + f" | {row['model']} | {row['n']} | " +
                     " | ".join(_pct(row[key]) for key in keys) + " |")
    reasons = payload.get("reasons") or []
    if reasons:
        lines.append("")
        lines.append("`functional_ok: null` reasons (group × reason):")
        lines.append("")
        lines.append("| Arm | " + " | ".join(reasons) + " |")
        lines.append("| --- | " + " | ".join(["---"] * len(reasons)) + " |")
        for label in sorted(payload["null_reasons"]):
            entry = payload["null_reasons"][label]
            lines.append("| " + label + " | " +
                         " | ".join(str(entry.get(reason, 0))
                                    for reason in reasons) + " |")
    return "\n".join(lines) + "\n"


def render_lockbud_md(payload, ds, ctx) -> str:
    joined = payload["joined"]
    ratios = payload["ratios"]
    lines = ["(a) Reference programs (`--fp-check`), by family:", "",
             "| Family | Tool | fixed FP | fixed n | buggy hits | buggy n |",
             "| --- | --- | --- | --- | --- | --- |"]
    reference_by_family = payload.get("reference_by_family", {})
    if reference_by_family:
        for family, entry in sorted(reference_by_family.items()):
            for tool in ("clippy", "lockbud"):
                row = entry[tool]
                lines.append(f"| {family} | {tool} | {row['fixed_hits']} | "
                             f"{row['fixed_n']} | {row['buggy_hits']} | "
                             f"{row['buggy_n']} |")
    else:
        lines.append("| (no --fp-check) | -- | -- | -- | -- | -- |")
    lines += ["", "(b) Experiment programs (STATIC v1 joined to the G0 oracle):",
              "",
              "| Group | tp | fp | fn | tn | recall | FP on ok | report on not-deadlock |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |",
              f"| pooled | {joined['tp']} | {joined['fp']} | {joined['fn']} | "
              f"{joined['tn']} | {_num(ratios['recall'])} | "
              f"{_num(ratios['fp_on_ok'])} | "
              f"{_num(ratios['report_on_not_deadlock'])} |"]
    for model, entry in sorted(payload["per_model"].items()):
        lines.append(f"| {model} | {entry['tp']} | {entry['fp']} | {entry['fn']} | "
                     f"{entry['tn']} | {_num(entry['recall'])} | "
                     f"{_num(entry['fp_on_ok'])} | "
                     f"{_num(entry['report_on_not_deadlock'])} |")
    for family, entry in sorted(payload["per_family"].items()):
        lines.append(f"| {family} | {entry['tp']} | {entry['fp']} | {entry['fn']} | "
                     f"{entry['tn']} | {_num(entry['recall'])} | "
                     f"{_num(entry['fp_on_ok'])} | "
                     f"{_num(entry['report_on_not_deadlock'])} |")
    lines += ["",
              f"no_g0 (no G0 counterpart) {joined['no_g0']}; "
              f"unavailable {joined['unavailable']}; excluded (v1 did not "
              f"compile) {joined['excluded']}."]
    return "\n".join(lines) + "\n"


def render_tests_md(payload, ds, ctx) -> str:
    lines = ["| Family | Comparison | b | c | p | p_Holm | Δ (pp) | 95% CI | n | missing (ref/ctrl) |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in payload["rows"]:
        missing = (f"{row['missing_reference']}/{row['missing_control']}"
                   if (row["missing_reference"] or row["missing_control"]) else "--")
        lines.append(f"| {row['family']} | {row['reference']} − {row['control']} | "
                     f"{row['b']} | {row['c']} | {_pval(row['p'])} | "
                     f"{_pval(row['p_holm'])} | {_pp_md(row['delta'])} | "
                     f"{_ci_md(row['ci_low'], row['ci_high'])} | {row['n_units']} | "
                     f"{missing} |")
    lines.append("")
    lines.append("Per comparison × model (paired Δ, within-model task-cluster "
                 "bootstrap 95% CI, b, c):")
    lines.append("")
    lines.append("| Comparison | Model | Δ (pp) | 95% CI | b | c |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for row in payload["rows"]:
        for model, entry in row["per_model_stats"].items():
            lines.append(
                f"| {row['reference']} − {row['control']} | {model} | "
                f"{_pp_md(entry['delta'])} | "
                f"{_ci_md(entry['ci_low'], entry['ci_high'])} | "
                f"{entry['b']} | {entry['c']} |")
    lines.append("")
    lines.append("Per comparison × tier (pooled models, paired Δ and "
                 "task-cluster bootstrap 95% CI):")
    lines.append("")
    lines.append("| Comparison | L1 | L2 | L3 | unclassified |")
    lines.append("| --- | --- | --- | --- | --- |")
    for row in payload["rows"]:
        cells = []
        for tier in ("L1", "L2", "L3", "unclassified"):
            entry = row["per_tier_stats"][tier]
            cells.append(f"{_pp_md(entry['delta'])} "
                         f"{_ci_md(entry['ci_low'], entry['ci_high'])}")
        lines.append(f"| {row['reference']} − {row['control']} | " +
                     " | ".join(cells) + " |")
    lines.append("")
    lines.append("Cochran's Q over the 7 groups (per model; only when "
                 "DYNAMIC_M covers every unit with all 6 main groups):")
    lines.append("")
    lines.append("| Model | Q | df | p | blocks | covered/total |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for model, entry in payload["dynamic_m_q"].items():
        lines.append(f"| {model} | {_num(entry['Q'])} | "
                     f"{'--' if entry['df'] is None else entry['df']} | "
                     f"{_pval(entry['p'])} | {entry['blocks']} | "
                     f"{entry['covered']}/{entry['total']} |")
    lines.append("")
    lines.append("Wilcoxon / A12 / Cliff's δ per comparison (tokens and calls; "
                 "X is the first group):")
    lines.append("")
    lines.append("| Comparison | Metric | Wilcoxon p | method | n | A12 | Cliff's δ |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for key, metric in payload["metrics"].items():
        for name in ("tokens", "calls"):
            entry = metric.get(name)
            if entry:
                lines.append(
                    f"| {key} | {name} | {_pval(entry['p'])} | {entry['method']} | "
                    f"{entry['n']} | {_num(entry['a12'])} | {_num(entry['cliffs'])} |")
    return "\n".join(lines) + "\n"


def render_numbers_md(payload, ds, ctx) -> str:
    return "\n".join([
        "| Macro | Value |", "| --- | --- |",
        f"| SNunits | {payload['units']} |",
        f"| SNcalls | {payload['calls']} |",
        f"| SNtokens | {payload['tokens']} |",
        f"| SNtruncpct | {_pct(payload['truncation'])} |",
        f"| SNincompletepct | {_pct(payload['incomplete'])} |",
        f"| SNshuttleunsup | {_pct(payload['shuttle_unsupported'])} |",
        f"| SNinstrunsup | {_pct(payload['instrument_unsupported'])} |",
        f"| SNlockbudfp | {_num(payload['lockbud_fp'])} |",
        f"| SNlook | {payload['look']} |",
        f"| SNalpha | {_num(payload['alpha'])} |",
    ]) + "\n"


TEX_RENDERERS = {
    "main": render_main_tex, "tiers": render_tiers_tex,
    "design": render_design_tex, "failures": render_failures_tex,
    "cost": render_cost_tex, "models": render_models_tex,
    "benchmark": render_benchmark_tex, "coverage": render_coverage_tex,
    "lockbud": render_lockbud_tex, "tests": render_tests_tex,
    "numbers": render_numbers_tex,
}
MD_RENDERERS = {
    "main": render_main_md, "tiers": render_tiers_md,
    "design": render_design_md, "failures": render_failures_md,
    "cost": render_cost_md, "models": render_models_md,
    "benchmark": render_benchmark_md, "coverage": render_coverage_md,
    "lockbud": render_lockbud_md, "tests": render_tests_md,
    "numbers": render_numbers_md,
}
TABLE_BUILDERS = {
    "main": table_main, "tiers": table_tiers, "design": table_design,
    "failures": table_failures, "cost": table_cost, "models": table_models,
    "benchmark": table_benchmark, "coverage": table_coverage,
    "lockbud": table_lockbud, "tests": table_tests, "numbers": table_numbers,
}
TEX_PATHS = {
    "main": "tables/main.tex", "tiers": "tables/tiers.tex",
    "design": "tables/ingredients.tex", "failures": "tables/failures.tex",
    "cost": "tables/cost.tex", "models": "tables/models.tex",
    "benchmark": "tables/benchmark.tex", "coverage": "extra/coverage.tex",
    "lockbud": "extra/lockbud.tex", "tests": "extra/tests.tex",
    "numbers": "extra/numbers.tex",
}
ALL_TABLES = list(TABLE_BUILDERS)


def build_report(run_dirs, ctx: ReportContext, tables, figure: bool = False):
    ds = load_runs(run_dirs, root=ctx.root,
                   allow_duplicates=ctx.allow_duplicates,
                   allow_mixed=ctx.allow_mixed)
    payloads = {}
    for name in tables:
        payloads[name] = TABLE_BUILDERS[name](ds, ctx)
    if figure:
        payloads["anytime"] = anytime_data(ds, ctx)
    return ds, payloads


def markdown_report(ds: Dataset, payloads: dict, tables, ctx: ReportContext) -> str:
    lines = ["# SkelNet analysis report", ""]
    lines.append("Runs: " + ", ".join(ds.run_ids) + ".")
    lines.append(f"Git: {ds.git_sha}. Pairing unit: (model, task, rep); "
                 "n = 3 unless noted.")
    lines.append("")
    lines.append("| Arm | included | skipped (excluded) | error (unsuccessful) |")
    lines.append("| --- | --- | --- | --- |")
    for label in sorted(ds.counts):
        entry = ds.counts[label]
        lines.append(f"| {label} | {entry['included']} | {entry['skipped']} | "
                     f"{entry['error']} |")
    lines.append("")
    for warning in ds.warnings:
        lines.append(f"> warning: {warning}")
    for message in ds.mixed:
        lines.append(f"> mixed: {message}")
    lines.append("")
    for name in tables:
        if name not in payloads:
            continue
        lines.append(f"## {name}")
        lines.append("")
        lines.append(MD_RENDERERS[name](payloads[name], ds, ctx))
    return "\n".join(lines)


def write_outputs(out: Path, ds: Dataset, payloads: dict, tables, *,
                  figure: bool, fmt: str, ctx: ReportContext) -> None:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if fmt in ("tex", "both"):
        for name in tables:
            path = out / TEX_PATHS[name]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(TEX_RENDERERS[name](payloads[name], ds, ctx),
                            encoding="utf-8")
        if figure:
            (out / "figures").mkdir(parents=True, exist_ok=True)
            (out / "figures" / "anytime.tex").write_text(
                render_anytime_tex(payloads["anytime"], ds, ctx),
                encoding="utf-8")
            (out / "data").mkdir(parents=True, exist_ok=True)
            (out / "data" / "anytime.csv").write_text(
                render_anytime_csv(payloads["anytime"]), encoding="utf-8")
    (out / "REPORT.md").write_text(markdown_report(ds, payloads, tables, ctx),
                                   encoding="utf-8")
    document = {
        "run_ids": ds.run_ids, "git_sha": ds.git_sha, "warnings": ds.warnings,
        "mixed": ds.mixed, "look": ctx.look, "tables": payloads,
    }
    (out / "report.json").write_text(
        json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
