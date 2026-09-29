"""``python -m skelnet stop-check`` — staged stopping rules (round 8).

Reuses :mod:`skelnet.report` for loading and derived fields.  Reads only run
directories, an optional price file, and the budget ledger; never calls a model
or the oracle.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import report, stats

MAIN_BASELINES = report.MAIN_BASELINES
STAGE1_GROUPS = ["SKEL", "CIR", "G0", "REFINE", "STATIC", "DYNAMIC"]
STAGE1_MODELS = 4
STAGE1_TASKS = 24
STAGE1_REPS = 3
FUTILITY_MARGIN = 0.03


def register(sub) -> None:
    parser = sub.add_parser("stop-check", help="staged stopping rules")
    parser.add_argument("run_dirs", nargs="+")
    parser.add_argument("--look", type=int, required=True, choices=[0, 1, 2, 3])
    parser.add_argument("--planned-units", type=int, default=880)
    parser.add_argument("--previous-look-units", type=int, default=528)
    parser.add_argument("--prices", default=None)
    parser.add_argument("--budget-file", default=None)
    parser.add_argument("--stage", type=int, default=0)
    parser.add_argument("--next-stage-units", type=int, default=None)
    parser.add_argument("--root", default=str(Path.cwd()))
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=cmd_stop_check)


def _ctx(args, prices) -> report.ReportContext:
    return report.ReportContext(
        root=Path(args.root), look=args.look, planned_units=args.planned_units,
        previous_look_units=args.previous_look_units, prices=prices,
        call_budget=5)


def cmd_stop_check(args) -> int:
    prices = None
    if args.prices:
        try:
            prices = json.loads(Path(args.prices).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"stop-check: cannot read --prices: {exc}", file=sys.stderr)
            return 2
    ctx = _ctx(args, prices)
    try:
        ds = report.load_runs(args.run_dirs, root=Path(args.root))
    except report.ReportInputError as exc:
        print(f"stop-check: {exc}", file=sys.stderr)
        return 2

    if args.look == 0:
        result = look0(ds, ctx, args)
    elif args.look == 1:
        result = look1(ds, ctx)
    else:
        result = look23(ds, ctx)
    result["spend"] = _spend(ds, ctx)
    if args.next_stage_units:
        result["projection"] = _next_projection(ds, ctx, args.next_stage_units)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(_markdown(result, args))
    return 0


# ── spend ────────────────────────────────────────────────────────────────

def _spend(ds: report.Dataset, ctx) -> dict:
    cells = [c for c in ds.cells if c.included]
    calls = [call for c in cells for call in (c.raw.get("calls") or [])]
    billable = sum(c.billable_tokens for c in cells)
    reasoning = sum(c.reasoning_tokens for c in cells)
    return {"calls": len(calls), "billable_tokens": billable,
            "reasoning_tokens": reasoning,
            "usd": _usd(ds, ctx)}


def _usd(ds: report.Dataset, ctx) -> float | None:
    if not ctx.prices:
        return None
    per_million = ctx.prices.get("per_million", {})
    total = 0.0
    for cell in ds.cells:
        if not cell.included:
            continue
        price = per_million.get(cell.model_id)
        if not price:
            return None
        cached = sum((call.get("usage") or {}).get("cached") or 0
                     for call in (cell.raw.get("calls") or []))
        uncached = max(0, cell.input_tokens - cached)
        total += (uncached * price.get("input", 0)
                  + cached * price.get("cached_input", price.get("input", 0))
                  + cell.output_tokens * price.get("output", 0)) / 1e6
    return total


def _next_projection(ds: report.Dataset, ctx, units: int) -> dict:
    cells = [c for c in ds.cells if c.included]
    if not cells:
        return {"units": units, "calls": None, "billable_tokens": None,
                "usd": None}
    per_unit_calls = sum(len(c.raw.get("calls") or []) for c in cells) / len(cells)
    per_unit_tokens = sum(c.billable_tokens for c in cells) / len(cells)
    usd = _usd(ds, ctx)
    per_unit_usd = usd / len(cells) if usd is not None else None
    return {"units": units, "calls": per_unit_calls * units,
            "billable_tokens": per_unit_tokens * units,
            "usd": per_unit_usd * units if per_unit_usd is not None else None}


# ── Look 0 ───────────────────────────────────────────────────────────────

def look0(ds: report.Dataset, ctx, args) -> dict:
    models = []
    for model in ds.models():
        cells = [c for c in ds.cells if c.model_id == model and c.included]
        calls = [call for c in cells for call in (c.raw.get("calls") or [])]
        truncated = sum(1 for call in calls
                        if call.get("truncation_retry")
                        or "length" in (call.get("finish_reasons") or []))
        empty = sum(1 for call in calls
                    if (call.get("usage") or {}).get("output") == 0
                    and not call.get("error"))
        transport = sum(1 for call in calls
                        if call.get("error") and "truncat" in str(call["error"]))
        first_round_miss = sum(1 for c in cells
                               if str(c.error or "").find("first_round_miss") >= 0)
        unavailable = sum(1 for c in cells
                          if any((layer or {}).get("status") == "unavailable"
                                 for layer in (c.raw.get("oracle", {})
                                               .get("layers") or {}).values()))
        rate = truncated / len(calls) if calls else None
        models.append({
            "model_id": model, "cells": len(cells), "calls": len(calls),
            "truncation_rate": rate, "truncation_flag": bool(
                rate is not None and rate > 0.02),
            "empty_reply_rate": empty / len(calls) if calls else None,
            "transport_truncated": transport,
            "first_round_miss": first_round_miss,
            "unavailable_layers": unavailable,
        })
    identity = any((manifest.get("failure") == "model_identity")
                   for manifest in ds.manifests)
    groups = []
    for label in report.GROUP_ORDER:
        cells = ds.included(label)
        if not cells:
            continue
        groups.append({
            "label": label, "n": len(cells),
            "calls": sum(len(c.raw.get("calls") or []) for c in cells) / len(cells),
            "billable": sum(c.billable_tokens for c in cells) / len(cells),
            "reasoning": sum(c.reasoning_tokens for c in cells) / len(cells),
            "llm_ms": sum(c.llm_wall_ms for c in cells) / len(cells),
            "tool_ms": _mean_optional([c.tool_wall_ms for c in cells]),
            "oracle_ms": _mean_optional([c.oracle_wall_ms for c in cells]),
        })
    coverage = report.table_coverage(ds, ctx)
    stage1 = _stage1_extrapolation(ds, ctx)
    ledger = _ledger_check(ds, args)
    return {"look": 0, "models": models, "identity_error": identity,
            "groups": groups, "coverage": coverage, "stage1": stage1,
            "ledger": ledger}


def _mean_optional(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _stage1_extrapolation(ds: report.Dataset, ctx) -> dict:
    n_units = STAGE1_TASKS * STAGE1_REPS
    rows = []
    for model in ds.models() or [None]:
        for label in STAGE1_GROUPS:
            cells = ds.included(label, model=model) if model else []
            note = None
            if not cells:
                cells = ds.included(label)
                note = "all-model average" if cells else "no data"
            if not cells:
                rows.append({"model_id": model, "label": label, "note": note})
                continue
            def mean(metric):
                return sum(metric(c) for c in cells) / len(cells)
            calls = mean(lambda c: len(c.raw.get("calls") or []))
            billable = mean(lambda c: c.billable_tokens)
            reasoning = mean(lambda c: c.reasoning_tokens)
            llm_ms = mean(lambda c: c.llm_wall_ms)
            oracle = _mean_optional([c.oracle_wall_ms for c in cells]) or 0.0
            rows.append({
                "model_id": model, "label": label, "note": note,
                "calls": calls * n_units,
                "billable_tokens": billable * n_units,
                "reasoning_tokens": reasoning * n_units,
                "llm_s": llm_ms * n_units / 1000.0,
                "oracle_s": oracle * n_units / 1000.0,
                "usd": _usd_for_cells(cells, ctx, n_units),
            })
    return {"units_per_group": n_units, "models": STAGE1_MODELS,
            "tasks": STAGE1_TASKS, "reps": STAGE1_REPS,
            "groups": STAGE1_GROUPS, "rows": rows}


def _usd_for_cells(cells, ctx, n_units):
    if not ctx.prices:
        return None
    per_million = ctx.prices.get("per_million", {})
    total = 0.0
    for cell in cells:
        price = per_million.get(cell.model_id)
        if not price:
            return None
        cached = sum((call.get("usage") or {}).get("cached") or 0
                     for call in (cell.raw.get("calls") or []))
        uncached = max(0, cell.input_tokens - cached)
        total += (uncached * price.get("input", 0)
                  + cached * price.get("cached_input", price.get("input", 0))
                  + cell.output_tokens * price.get("output", 0)) / 1e6
    return total / len(cells) * n_units


def _ledger_check(ds: report.Dataset, args) -> dict:
    if not args.budget_file:
        return {"checked": False}
    path = Path(args.budget_file)
    if not path.exists():
        return {"checked": False, "reason": "budget file missing"}
    data = json.loads(path.read_text(encoding="utf-8"))
    stage = str(args.stage)
    requests = ((data.get("stages") or {}).get(stage) or {}).get("requests")
    lower = upper = 0
    for cell in ds.cells:
        if not cell.included:
            continue
        for call in cell.raw.get("calls") or []:
            if call.get("cache_hit"):
                continue
            reasons = call.get("finish_reasons") or []
            lower += max(1, len(reasons))
            transport = call.get("transport_attempt") or 1
            upper += max(1, len(reasons)) + max(0, transport - 1)
    consistent = requests is None or lower <= requests <= upper
    return {"checked": True, "stage": stage, "ledger_requests": requests,
            "lower": lower, "upper": upper, "consistent": consistent}


# ── Look 1 ───────────────────────────────────────────────────────────────

def look1(ds: report.Dataset, ctx) -> dict:
    skel = ds.rate("SKEL", lambda c: c.ok)
    best = None
    best_label = None
    for label in MAIN_BASELINES:
        rate = ds.rate(label, lambda c: c.ok)
        if rate is not None and (best is None or rate > best):
            best, best_label = rate, label
    margin = None if skel is None or best is None else skel - best
    futility = margin is not None and margin < FUTILITY_MARGIN
    return {"look": 1, "skel_rate": skel, "best_baseline": best_label,
            "best_rate": best, "margin": margin, "futility": futility,
            "failure_stages": _failure_stages(ds)}


def _failure_stages(ds: report.Dataset) -> dict:
    stages = {"parse": 0, "check": 0, "verify": 0, "rust_compile": 0,
              "oracle": 0}
    for cell in ds.cells:
        if not cell.included:
            continue
        raw = cell.raw
        if not raw.get("parse_ok"):
            stages["parse"] += 1
        elif not raw.get("check_ok"):
            stages["check"] += 1
        elif raw.get("skel_verified") is False and raw.get("arm") in ("SKEL", "CIR"):
            stages["verify"] += 1
        elif raw.get("rust_compiled") is False:
            stages["rust_compile"] += 1
        elif cell.ok is False:
            stages["oracle"] += 1
    return stages


# ── Look 2 / 3 ───────────────────────────────────────────────────────────

def _ok_units(ds, reference, control, predicate):
    index = {}
    for label in (reference, control):
        for cell in ds.included(label):
            index.setdefault((label, cell.model_id, cell.task, cell.rep), cell)
    units = []
    for (label, model, task, rep), cell in index.items():
        if label != reference:
            continue
        other = index.get((control, model, task, rep))
        if other is None:
            continue
        units.append((task, int(predicate(cell)) - int(predicate(other))))
    return units


def look23(ds: report.Dataset, ctx) -> dict:
    alpha = report.nominal_alpha(ds, ctx)
    family1 = []
    comparisons = {}
    for label in MAIN_BASELINES:
        comparisons[label] = report._comparison(ds, "SKEL", label, ctx)
        family1.append(comparisons[label]["p"])
    holm = stats.holm(family1)
    p_holm = dict(zip(MAIN_BASELINES, holm))
    units = report._main_paired_units(ds)
    t = units / ctx.planned_units

    criteria = {}
    criteria["1_holm"] = {
        "ok": alpha is not None and all(
            p_holm[label] < alpha for label in MAIN_BASELINES),
        "alpha": alpha, "p_holm": p_holm, "units": units, "t": t}
    model_ok = {}
    for label in MAIN_BASELINES:
        per_model = comparisons[label]["per_model_delta"]
        wins = sum(1 for value in per_model.values()
                   if value is not None and value > 0)
        model_ok[label] = {"wins": wins, "of": len(per_model),
                           "per_model": per_model}
    criteria["2_per_model"] = {
        "ok": all(entry["wins"] >= 3 and entry["of"] >= 4
                  for entry in model_ok.values()),
        "detail": model_ok}
    tiers = {}
    for label in MAIN_BASELINES:
        subset = _tier_units(ds, label)
        tiers[label] = (sum(d for _, d in subset) / len(subset)
                        if subset else None)
    criteria["3_l2l3"] = {
        "ok": all(value is not None and value > 0 for value in tiers.values()),
        "deltas": tiers}
    sens = {}
    for label in MAIN_BASELINES:
        subset = _ok_units(ds, "SKEL", label, lambda c: c.sens)
        sens[label] = (sum(d for _, d in subset) / len(subset)
                       if subset else None)
    criteria["4_sensitivity"] = {
        "ok": all(value is not None and value > 0 for value in sens.values()),
        "deltas": sens}
    criteria["5_ci"] = {
        "ok": all(comparisons[label]["ci_low"] is not None
                  and comparisons[label]["ci_low"] > 0
                  for label in MAIN_BASELINES),
        "ci": {label: [comparisons[label]["ci_low"],
                       comparisons[label]["ci_high"]]
               for label in MAIN_BASELINES}}
    dynamic_m = report._comparison(ds, "SKEL", "DYNAMIC_M", ctx)
    criteria["6_dynamic_m"] = {
        "delta": dynamic_m["delta"],
        "ci": [dynamic_m["ci_low"], dynamic_m["ci_high"]],
        "note": ("DYNAMIC_M is significantly better; narrow the claim per "
                 "§3.5(6)" if (dynamic_m["ci_low"] is not None
                               and dynamic_m["ci_low"] < 0
                               and dynamic_m["ci_high"] is not None
                               and dynamic_m["ci_high"] < 0) else None)}

    worst = None
    for label in MAIN_BASELINES:
        value = tiers[label]
        if value is not None and (worst is None or value < worst):
            worst = value
    futility = ctx.look == 2 and worst is not None and worst < 0
    success = all(criteria[key]["ok"] for key in
                  ("1_holm", "2_per_model", "3_l2l3", "4_sensitivity", "5_ci"))
    verdict = "futility" if futility else ("success" if success else "continue")
    return {"look": ctx.look, "criteria": criteria, "verdict": verdict,
            "alpha": alpha, "units": units}


def _tier_units(ds, control):
    index = {}
    for label in ("SKEL", control):
        for cell in ds.included(label):
            if cell.tier in ("L2", "L3"):
                index[(label, cell.model_id, cell.task, cell.rep)] = cell
    units = []
    for (label, model, task, rep), cell in index.items():
        if label != "SKEL":
            continue
        other = index.get((control, model, task, rep))
        if other is not None:
            units.append((task, int(cell.ok) - int(other.ok)))
    return units


# ── rendering ────────────────────────────────────────────────────────────

def _markdown(result: dict, args) -> str:
    look = result["look"]
    lines = [f"# stop-check (Look {look})", ""]
    spend = result["spend"]
    lines.append(f"Spend: calls={spend['calls']}, "
                 f"billable_tokens={spend['billable_tokens']}, "
                 f"reasoning_tokens={spend['reasoning_tokens']}, "
                 f"usd={spend['usd']}.")
    lines.append("")
    if look == 0:
        lines.append("| Model | cells | calls | truncation | empty | first_round_miss | transport_trunc | unavailable |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for row in result["models"]:
            flag = " **" if row["truncation_flag"] else ""
            lines.append(f"| {row['model_id']} | {row['cells']} | {row['calls']} | "
                         f"{_pct(row['truncation_rate'])}{flag} | "
                         f"{_pct(row['empty_reply_rate'])} | "
                         f"{row['first_round_miss']} | {row['transport_truncated']} | "
                         f"{row['unavailable_layers']} |")
        lines.append("")
        lines.append(f"Model identity error: {result['identity_error']}.")
        lines.append("")
        lines.append("Stage 1 extrapolation (24 tasks x 4 models x 3 reps x 6 groups):")
        lines.append("")
        lines.append("| Model | Group | calls | billable | reasoning | LLM s | oracle s | USD | note |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for row in result["stage1"]["rows"]:
            if "calls" not in row:
                lines.append(f"| {row['model_id']} | {row['label']} | -- | -- | -- | -- | -- | -- | {row.get('note')} |")
                continue
            usd = "--" if row["usd"] is None else f"{row['usd']:.2f}"
            lines.append(f"| {row['model_id']} | {row['label']} | {row['calls']:.0f} | "
                         f"{row['billable_tokens']:.0f} | {row['reasoning_tokens']:.0f} | "
                         f"{row['llm_s']:.1f} | {row['oracle_s']:.1f} | {usd} | "
                         f"{row.get('note') or ''} |")
        ledger = result["ledger"]
        lines.append("")
        if ledger.get("checked"):
            lines.append(f"Ledger: requests={ledger['ledger_requests']}, "
                         f"allowed [{ledger['lower']}, {ledger['upper']}], "
                         f"consistent={ledger['consistent']}.")
        else:
            lines.append(f"Ledger: not checked ({ledger.get('reason', 'no --budget-file')}).")
    elif look == 1:
        lines.append(f"SKEL {_pct(result['skel_rate'])} vs best baseline "
                     f"{result['best_baseline']} {_pct(result['best_rate'])}; "
                     f"margin {_pct(result['margin'])}; "
                     f"futility={result['futility']}.")
        lines.append("")
        lines.append("Failure stages: " + ", ".join(
            f"{k}={v}" for k, v in result["failure_stages"].items()) + ".")
    else:
        lines.append(f"Verdict: **{result['verdict']}**; units={result['units']}, "
                     f"nominal alpha={result['alpha']}.")
        lines.append("")
        lines.append("| Criterion | Met | Detail |")
        lines.append("| --- | --- | --- |")
        for name, entry in result["criteria"].items():
            met = entry.get("ok", entry.get("note") is None)
            lines.append(f"| {name} | {met} | {json.dumps(entry, sort_keys=True)} |")
    if "projection" in result:
        projection = result["projection"]
        lines.append("")
        lines.append(f"Next-stage projection ({projection['units']} units): "
                     f"calls={projection['calls']}, "
                     f"tokens={projection['billable_tokens']}, "
                     f"usd={projection['usd']}.")
    return "\n".join(lines) + "\n"


def _pct(value):
    return "--" if value is None else f"{value * 100:.1f}"


if __name__ == "__main__":  # pragma: no cover
    sys.exit(0)
