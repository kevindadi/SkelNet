"""Baseline arms: REFINE, STATIC, DYNAMIC, DYNAMIC_M.

In-group acceptance uses this module's feedback tools (and the shared compile
check). The oracle scores the final Rust only after the loop, on ``<cell>/``,
which is a different directory from ``<cell>/feedback/`` and ``<cell>/compile/``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from .providers import CandidateRequest
from .rusttools.clippy import render_clippy_sections, run_clippy
from .rusttools.dynamic_feedback import pack_sections, run_dynamic
from .rusttools.lockbud import render_lockbud_section, run_lockbud
from .rusttools.monitor_feedback import run_monitor_feedback
from .rusttools.runner import ToolRunner

_SOURCE_FOR_ARM = {
    "STATIC": "static",
    "DYNAMIC": "dynamic",
    "DYNAMIC_M": "dynamic_monitor",
}


@dataclass
class _Feedback:
    passed: bool
    reason: str
    feedback: str
    truncated: bool
    tools: dict = field(default_factory=dict)
    seeds: dict = field(default_factory=dict)


def _sha(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _nbytes(text: str | None) -> int:
    return len((text or "").encode("utf-8"))


def _round(call: int, stage: str, reply_kind: str, version: int,
           compiled: bool | None, feedback: str | None, *,
           compile: str | None = None, truncated: bool = False,
           tools: dict | None = None, seeds: dict | None = None) -> dict:
    text = feedback or ""
    return {
        "call": call,
        "stage": stage,
        "reply_kind": reply_kind,
        "version": version,
        "compiled": compiled,
        "compile": compile,
        "tools": tools or {},
        "seeds": seeds or {},
        "feedback_sha256": _sha(text),
        "feedback_bytes": _nbytes(text),
        "truncated": truncated or "[truncated]" in text,
    }


def _compile_disposition(compiled_result) -> tuple[bool | None, str]:
    """Classify one ``compile_rust`` result the same way SKEL/CIR do.

    ``unavailable`` or ``timed_out`` is not a compile failure: the compiler
    never produced a verdict. A non-zero cargo exit with no compiler error is
    already reported as ``unavailable`` by ``compile_rust``.
    """
    if getattr(compiled_result, "unavailable", None):
        return None, "unavailable"
    if getattr(compiled_result, "timed_out", False):
        return None, "timeout"
    ok = bool(getattr(compiled_result, "ok", False))
    return ok, "ok" if ok else "error"


def _static_feedback(tools, directory, source, *, timeout: float) -> _Feedback:
    clippy = run_clippy(tools, Path(directory) / "clippy", source, timeout=timeout)
    lockbud = run_lockbud(tools, Path(directory) / "lockbud", source, timeout=timeout)
    sections = render_clippy_sections(clippy)
    sections.append(render_lockbud_section(lockbud))
    text, truncated = pack_sections(sections)
    clippy_status = "unavailable" if clippy.unavailable else (
        "fail" if clippy.blocking else "pass")
    lock_status = "unavailable" if lockbud.unavailable else (
        "fail" if lockbud.blocking else "pass")
    clippy_cat = clippy.clippy[0].code if clippy.clippy else (
        clippy.rustc_errors[0].code if clippy.rustc_errors else None)
    lock_cat = lockbud.hits[0].bug_kind if lockbud.hits else None
    return _Feedback(
        passed=not clippy.blocking and not lockbud.blocking,
        reason="static_clean",
        feedback=text, truncated=truncated,
        tools={"clippy": {"status": clippy_status, "category": clippy_cat},
               "lockbud": {"status": lock_status, "category": lock_cat}},
    )


def _dynamic_feedback(tools, directory, source, *, terminal, timeout, miri_seed_count
                      ) -> _Feedback:
    result = run_dynamic(
        tools, directory, source, terminal=terminal, timeout=timeout,
        miri_seed_count=miri_seed_count)
    tools_map = {s.name: {"status": s.status, "category": s.category}
                 for s in result.slices}
    return _Feedback(passed=result.passed, reason="dynamic_pass",
                     feedback=result.feedback, truncated=result.truncated,
                     tools=tools_map, seeds=dict(result.seeds))


def _monitor_and_dynamic(tools, directory, source, *, terminal, task_dir, timeout,
                         miri_seed_count, property_ids, id_index) -> _Feedback:
    dynamic = _dynamic_feedback(
        tools, Path(directory) / "dynamic", source, terminal=terminal,
        timeout=timeout, miri_seed_count=miri_seed_count)
    monitor = run_monitor_feedback(
        tools, Path(directory) / "monitor", source, task_dir=task_dir,
        property_ids=property_ids, timeout=timeout, id_index=id_index)
    text, truncated = pack_sections([dynamic.feedback, monitor.feedback])
    tools_map = dict(dynamic.tools)
    tools_map["monitor"] = {"status": monitor.status, "category": monitor.category}
    return _Feedback(
        passed=dynamic.passed and not monitor.blocking,
        reason="dynamic_monitor_pass",
        feedback=text,
        truncated=truncated or dynamic.truncated or monitor.truncated,
        tools=tools_map,
        seeds=dynamic.seeds,
    )


def run_baseline_cell(*, arm: str, task: str, requirements: str, task_dir,
                      terminal, provider, oracle, workdir, replicate: int,
                      run_params, tools=None, compile_fn=None,
                      feedback_tools=None, tools_missing=None,
                      miri_seed_count: int = 16, timeout: float = 180.0):
    """Run one baseline cell. ``feedback_tools`` is only for tests; the real
    path leaves it ``None`` and calls the tool modules above.
    """
    feedback_fn, accept_reason_name = _select_feedback(
        arm, tools if tools is not None else ToolRunner(),
        terminal=terminal, task_dir=task_dir, timeout=timeout,
        miri_seed_count=miri_seed_count, run_params=run_params,
        feedback_tools=feedback_tools)
    return run_rust_iter_cell(
        arm=arm, task=task, requirements=requirements, provider=provider,
        oracle=oracle, workdir=Path(workdir), replicate=replicate,
        run_params=run_params, tools=tools if tools is not None else ToolRunner(),
        compile_fn=compile_fn, feedback_fn=feedback_fn,
        tools_missing=list(tools_missing or []), timeout=timeout)


def _select_feedback(arm, tools, *, terminal, task_dir, timeout, miri_seed_count,
                     run_params, feedback_tools):
    if feedback_tools is not None:
        return feedback_tools, "injected"
    property_ids = getattr(run_params, "property_ids", "keep")
    id_index: dict[str, str] = {}

    def static_fn(source, directory):
        return _static_feedback(tools, directory, source, timeout=timeout)

    def dynamic_fn(source, directory):
        return _dynamic_feedback(tools, directory, source, terminal=terminal,
                                 timeout=timeout, miri_seed_count=miri_seed_count)

    def monitor_fn(source, directory):
        return _monitor_and_dynamic(
            tools, directory, source, terminal=terminal, task_dir=task_dir,
            timeout=timeout, miri_seed_count=miri_seed_count,
            property_ids=property_ids, id_index=id_index)

    return {"STATIC": static_fn, "DYNAMIC": dynamic_fn,
            "DYNAMIC_M": monitor_fn, "REFINE": None}[arm], arm


def run_rust_iter_cell(*, arm, task, requirements, provider, oracle, workdir,
                       replicate, run_params, tools, compile_fn, feedback_fn,
                       tools_missing, timeout: float = 180.0):
    """Shared Rust iteration loop for the four baseline arms."""
    from .pipeline import CellResult, classify_rust_reply
    from .prompts import FORMAT_RETRY_NOTE
    from .rusttools.compile import compile_rust, render_compile_errors

    if compile_fn is None:
        compile_fn = compile_rust
    result = CellResult(arm=arm, task=task, replicate=replicate, rust_mode="llm")
    budget = int(run_params.call_budget)
    rounds: list[dict] = []
    source: str | None = None
    version = 0
    compiled = False
    any_compiled = False
    accepted = False
    accepted_at = None
    accept_reason = None
    stage = "generate"
    feedback: str | None = None
    current = None
    pending = False
    first_kind = None

    def assess() -> None:
        nonlocal pending, accepted, accepted_at, accept_reason, stage, feedback, current
        if not pending or feedback_fn is None or source is None:
            pending = False
            return
        pending = False
        directory = Path(workdir) / "feedback" / f"r{rounds[-1]['call']}"
        directory.mkdir(parents=True, exist_ok=True)
        outcome = feedback_fn(source, directory)
        rounds[-1]["tools"] = outcome.tools
        rounds[-1]["seeds"] = outcome.seeds
        rounds[-1]["feedback_sha256"] = _sha(outcome.feedback)
        rounds[-1]["feedback_bytes"] = _nbytes(outcome.feedback)
        rounds[-1]["truncated"] = outcome.truncated
        if outcome.passed:
            accepted = True
            accepted_at = rounds[-1]["call"]
            accept_reason = outcome.reason
            return
        stage = "tool_feedback"
        feedback = outcome.feedback
        current = source

    for call in range(1, budget + 1):
        assess()
        if accepted:
            break
        response = provider.propose(CandidateRequest(
            requirements=requirements, contract=None, feedback=feedback,
            attempt=call, stage=stage, current_program=current,
            previous_candidate=current))
        result.rounds_used = call
        if response.error:
            rounds.append(_round(call, stage, "error", version, compiled, feedback))
            result.history.append({"call": call, "stage": stage,
                                   "reply_kind": "error", "version": version})
            result.error = response.error
            accept_reason = "model_error"
            break
        allow_no_issues = arm == "REFINE" and stage == "review" and compiled
        reply = classify_rust_reply(response.text, allow_no_issues=allow_no_issues)
        if first_kind is None:
            first_kind = reply.kind
        if reply.kind == "no_issues":
            rounds.append(_round(call, stage, "no_issues", version, compiled, feedback))
            result.history.append({"call": call, "stage": stage,
                                   "reply_kind": "no_issues", "version": version})
            accepted = True
            accepted_at = call
            accept_reason = "no_issues"
            break
        if reply.kind != "program":
            rounds.append(_round(call, stage, "other", version, compiled, feedback))
            result.history.append({"call": call, "stage": stage,
                                   "reply_kind": "other", "version": version})
            feedback = FORMAT_RETRY_NOTE if not feedback else (
                FORMAT_RETRY_NOTE + "\n" + feedback)
            continue
        version += 1
        source = reply.source
        current = source
        compile_dir = Path(workdir) / "compile" / f"c{version}"
        compile_dir.mkdir(parents=True, exist_ok=True)
        compiled_result = compile_fn(tools, compile_dir, source)
        compiled, compile_kind = _compile_disposition(compiled_result)
        if compiled is None:
            # The compiler did not run. Stop; do not ask for rust_fix.
            rounds.append(_round(call, stage, "program", version, None, None,
                                 compile=compile_kind))
            result.history.append({"call": call, "stage": stage,
                                   "reply_kind": "program", "version": version,
                                   "compiled": None})
            cell_error = ("compile_timeout" if compile_kind == "timeout"
                          else "compile_unavailable")
            if not result.error:
                result.error = cell_error
            accept_reason = cell_error
            break
        if compiled:
            any_compiled = True
        outgoing = "" if compiled else render_compile_errors(compiled_result)
        rounds.append(_round(call, stage, "program", version, compiled, outgoing,
                             compile=compile_kind))
        result.history.append({"call": call, "stage": stage,
                               "reply_kind": "program", "version": version,
                               "compiled": compiled})
        if not compiled:
            stage = "rust_fix"
            feedback = outgoing
            pending = False
            continue
        if arm == "REFINE":
            stage = "review"
            feedback = None
            pending = False
            continue
        pending = True
    if pending and not accepted and not result.error:
        assess()

    result.rust = source
    result.candidate = source
    result.accepted = accepted
    result.parse_ok = first_kind == "program"
    result.check_ok = any_compiled
    if not accepted and accept_reason is None:
        accept_reason = "budget_exhausted"
    if source:
        result.oracle = oracle.evaluate(source, workdir)
    calls = getattr(provider, "calls", None) or []
    cache_hit = None
    if calls and isinstance(calls[0], dict) and "cache_hit" in calls[0]:
        cache_hit = bool(calls[0]["cache_hit"])
    payload = {
        "rounds": rounds,
        "accepted_at_call": accepted_at,
        "accept_reason": accept_reason,
        "final_version": version,
        "first_round_cache_hit": cache_hit,
        "tools_missing": list(tools_missing),
    }
    extra = getattr(result, "extra", None)
    if not isinstance(extra, dict):
        result.extra = {}
    result.extra["baseline"] = payload
    return result
