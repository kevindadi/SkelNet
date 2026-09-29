"""The three experimental arms with a single shared revision loop.

- ``G0``  : requirements -> LLM writes Rust directly (baseline).
- ``SKEL``: requirements -> LLM writes a ``.skel`` skeleton -> check/verify
  (contract hidden) -> remapped feedback -> revise (<= N rounds) -> accepted
  skeleton + requirements -> Rust (LLM, or deterministic ``skelnet codegen``).
- ``CIR`` : as SKEL, but the LLM writes ConcIR JSON directly (Rust via LLM or
  ``concir-backend codegen``).

All arms' final Rust is scored by the same ``oracle``. The skeleton/CIR
verification evidence is recorded separately. No real LLM is called in tests.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import evidence, prompts
from .oracle import oracle_result_dict
from .providers import CandidateProvider, CandidateRequest
from .rusttools.compile import render_compile_errors


@dataclass
class CellResult:
    arm: str
    task: str
    replicate: int
    accepted: bool = False
    candidate: str | None = None
    rust: str | None = None
    rust_mode: str = "llm"
    cir_trace: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    oracle: Any = None
    ledger: dict[str, Any] = field(default_factory=dict)
    evidence_sufficient: bool = False
    parse_ok: bool = False
    check_ok: bool = False
    rounds_used: int = 0
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


_LANG_ALIASES = {
    "rust": frozenset({"rust", "rs"}),
    "skel": frozenset({"skel", "skeleton"}),
    "json": frozenset({"json", "jsonc"}),
}
_FENCE_OPEN = re.compile(r"```([^\n]*)")
_LANG_TOKEN = re.compile(r"([A-Za-z0-9_+.-]+)")


def _fence_body(text: str, info_end: int) -> str:
    """Code after an opening fence, without the info-string line."""
    rest = text[info_end:]
    if rest.startswith("\r\n"):
        rest = rest[2:]
    elif rest.startswith("\n"):
        rest = rest[1:]
    close = rest.find("```")
    if close < 0:
        return rest.strip()
    return rest[:close].strip()


def _extract_block(text: str, language: str) -> str:
    """Extract a fenced block for ``language``.

    Prefer the first fence whose info-string's first word is a known alias
    (case-insensitive). Otherwise use the first fence of any kind. The info
    string itself is not part of the result. An unclosed fence runs to the
    end of the reply. With no fence, the whole reply is returned.
    """
    aliases = _LANG_ALIASES[language]
    opens = list(_FENCE_OPEN.finditer(text or ""))
    if not opens:
        return (text or "").strip()

    def token(info: str) -> str:
        match = _LANG_TOKEN.search(info or "")
        return match.group(1).lower() if match else ""

    chosen = next((item for item in opens if token(item.group(1)) in aliases), None)
    if chosen is None:
        chosen = opens[0]
    return _fence_body(text, chosen.end())


def extract_skel(text: str) -> str:
    return _extract_block(text, "skel")


def extract_rust(text: str) -> str:
    return _extract_block(text, "rust")


def extract_cir(text: str) -> str:
    """Extract a ConcIR JSON object from a fenced ```json block (or bare text)."""
    return _extract_block(text, "json")


def _has_parse_error(check: Any) -> bool:
    for d in (check.payload or {}).get("diagnostics", []) or []:
        if str(d.get("code", "")) in ("S001", "S002", "S003"):
            return True
    return False


@dataclass
class RustReply:
    """Classification of a Rust-stage model reply."""

    kind: str  # "program" | "no_issues" | "other"
    source: str | None = None


_FENCE_RE = re.compile(r"```([A-Za-z0-9_+.-]*)")
_RUST_FENCE_RE = re.compile(r"```\s*(?:rust|rs)\b", re.IGNORECASE)


def classify_rust_reply(text: str, *, allow_no_issues: bool = False) -> RustReply:
    """Classify a Rust reply: a program, an explicit ``NO_ISSUES``, or other.

    ``allow_no_issues`` is only set by arms whose Rust stage may legitimately
    return "no issues"; the reply must reduce to exactly ``NOISSUES`` after
    dropping every non-letter character (so ``NO_ISSUES``/``No issues.`` match).

    A reply with no ```rust block whose first code block carries a non-rust
    language tag (e.g. ```skel/```json) is ``other``: the skeleton DSL itself
    contains ``fn main`` and must not be mistaken for a program.
    """
    if allow_no_issues:
        letters = re.sub(r"[^A-Za-z]", "", text or "")
        if letters.upper() == "NOISSUES":
            return RustReply(kind="no_issues")
    body = text or ""
    if not _RUST_FENCE_RE.search(body):
        first = _FENCE_RE.search(body)
        if first and first.group(1) and first.group(1).lower() not in ("rust", "rs"):
            return RustReply(kind="other")
    source = extract_rust(body)
    if source and "fn main" in source:
        return RustReply(kind="program", source=source)
    return RustReply(kind="other")


def _ms_since(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _skel_verify(backend, path: Path, contract_path: Path) -> Any:
    started = time.monotonic()
    check = backend.check(path)
    check_ms = _ms_since(started)
    if not check.ok:
        return check, None, check_ms, None
    started = time.monotonic()
    verify = backend.verify(path, contract_path)
    return check, verify, check_ms, _ms_since(started)


def _design_kind(arm: str) -> str | None:
    return {"SKEL": "skel", "CIR": "cir"}.get(arm)


def _run_rust_stage(*, arm: str, rust_mode: str, design: str | None,
                    design_path: Path | None, requirements: str,
                    provider: CandidateProvider, backend: Any, oracle: Any,
                    workdir: Path, calls_used: int, call_budget: int,
                    rust_when_unverified: str, skel_verified: bool,
                    last_check_ok: bool, compile_fn, tools,
                    result: CellResult) -> tuple:
    """Run the Rust stage for one cell. Returns (rust, trace, oracle, error, extra)."""
    extra: dict[str, Any] = {
        "skel_verified": skel_verified,
        "rust_when_unverified": rust_when_unverified,
        "rust_compiled": None,
        "rust_calls": 0,
        "rust_attempts": [],
        "rust_skipped": None,
    }
    if design is None or design_path is None:
        extra["rust_skipped"] = "no_candidate"
        return None, None, None, None, extra

    if rust_mode == "codegen":
        # Deterministic codegen needs a skeleton that at least passes `check`.
        if not last_check_ok:
            extra["rust_skipped"] = "skeleton_invalid"
            return None, None, None, None, extra
        if arm == "CIR":
            art = backend.codegen_cir(design_path, workdir / "codegen")
        else:
            art = backend.codegen_skel(design_path, workdir / "codegen")
        if not art.ok:
            extra["rust_skipped"] = "codegen_failed"
            return None, None, None, art.error, extra
        extra["rust_compiled"] = True
        trace = art.trace_rs
        files = {"src/cir_trace.rs": trace} if trace else None
        # Codegen has no task-specific terminal line: build + clean exit only.
        result = oracle.evaluate(art.main_rs, workdir, extra_files=files,
                                 check_terminal=False)
        return art.main_rs, trace, result, None, extra

    if not skel_verified and rust_when_unverified == "skip":
        extra["rust_skipped"] = "unverified"
        return None, None, None, None, extra

    current_program: str | None = None
    compiled: bool | None = None
    compile_errors: str | None = None
    format_note = False
    error: str | None = None
    while calls_used + extra["rust_calls"] < call_budget:
        stage = "rust" if current_program is None else "rust_fix"
        feedback = None
        if format_note:
            feedback = prompts.FORMAT_RETRY_NOTE
            if compile_errors:
                feedback += "\n\n" + compile_errors
        elif compile_errors:
            feedback = compile_errors
        request = CandidateRequest(
            requirements=requirements, contract=None, feedback=feedback,
            attempt=calls_used + extra["rust_calls"] + 1, previous_candidate=design,
            current_program=current_program, stage=stage)
        response = provider.propose(request)
        if response.error:
            error = response.error
            break
        extra["rust_calls"] += 1
        call_number = calls_used + extra["rust_calls"]
        reply = classify_rust_reply(response.text)
        entry = {"call": call_number, "stage": stage, "reply_kind": reply.kind,
                 "compiled": None, "compile": None, "compile_wall_ms": None}
        if reply.kind == "program":
            current_program = reply.source
            compiled_result = compile_fn(
                tools, workdir / "compile" / f"c{call_number}", current_program)
            entry["compile_wall_ms"] = getattr(compiled_result, "wall_ms", None)
            if compiled_result.unavailable:
                # The compiler itself could not run: stop, never retry.
                entry["compile"] = "unavailable"
                extra["rust_attempts"].append(entry)
                result.history.append({"attempt": extra["rust_calls"],
                                       "stage": stage, "compiled": None})
                compiled = None
                if not error:
                    error = "compile_unavailable"
                break
            if compiled_result.timed_out:
                entry["compile"] = "timeout"
                extra["rust_attempts"].append(entry)
                result.history.append({"attempt": extra["rust_calls"],
                                       "stage": stage, "compiled": None})
                compiled = None
                if not error:
                    error = "compile_timeout"
                break
            entry["compiled"] = bool(compiled_result.ok)
            entry["compile"] = "ok" if compiled_result.ok else "error"
            compiled = bool(compiled_result.ok)
            extra["rust_attempts"].append(entry)
            result.history.append({"attempt": extra["rust_calls"], "stage": stage,
                                   "compiled": bool(compiled_result.ok)})
            if compiled_result.ok:
                break
            compile_errors = render_compile_errors(compiled_result)
            format_note = False
        else:
            extra["rust_attempts"].append(entry)
            compiled = False if current_program is not None else None
            result.history.append({"attempt": extra["rust_calls"], "stage": stage,
                                   "compiled": None})
            format_note = True
    if current_program is None:
        extra["rust_skipped"] = "no_program"
        extra["rust_compiled"] = None
        return None, None, None, error, extra
    extra["rust_compiled"] = compiled
    oracle_result = oracle.evaluate(current_program, workdir)
    return current_program, None, oracle_result, error, extra


def run_skel_cell(*, task: str, requirements: str, contract_path: Path,
                  provider: CandidateProvider, backend: Any, oracle: Any,
                  workdir: Path, rounds: int = 4, replicate: int = 0,
                  rust_mode: str = "llm", call_budget: int = 5,
                  rust_when_unverified: str = "last", feedback_mode: str = "full",
                  property_ids: str = "keep", compile_fn=None,
                  tools=None) -> CellResult:
    result = CellResult(arm="SKEL", task=task, replicate=replicate, rust_mode=rust_mode)
    feedback: str | None = None
    candidate: str | None = None
    last_nonempty: str | None = None
    last_path: Path | None = None
    last_check_ok = False
    last_status: str | None = None
    property_index: dict[str, str] = {}
    attempts = max(1, min(rounds, call_budget - 1))
    for attempt in range(1, attempts + 1):
        result.rounds_used = attempt
        response = provider.propose(CandidateRequest(
            requirements=requirements, contract=None, feedback=feedback,
            attempt=attempt, previous_candidate=candidate, stage="skel"))
        if response.error:
            result.error = response.error
            break
        candidate = extract_skel(response.text)
        result.candidate = candidate
        # Always write and check the reply, even an empty one (9dfaefe), but
        # only a non-empty reply can drive the Rust stage (D5-6).
        skel_path = workdir / f"candidate_{attempt}.skel"
        skel_path.write_text(candidate, encoding="utf-8")
        check, verify, check_ms, verify_ms = _skel_verify(backend, skel_path, contract_path)
        if attempt == 1:
            result.parse_ok = bool(candidate) and check.kind == "semantic" and not _has_parse_error(check)
        if check.ok:
            result.check_ok = True
        if candidate:
            last_nonempty = candidate
            last_path = skel_path
            last_check_ok = check.ok
        if verify is None:
            if candidate:
                last_status = "check_failed"
            feedback = prompts.render_feedback(prompts.build_check_feedback(
                check, property_ids=property_ids, index=property_index))
            result.history.append({"attempt": attempt, "stage": "check",
                                   "status": check.status,
                                   "diagnostics": (check.payload or {}).get("diagnostics"),
                                   "wall_ms": check_ms})
            continue
        result.history.append({"attempt": attempt, "stage": "verify",
                               "outcome": verify.outcome, "complete": verify.complete,
                               "unmapped": (verify.payload or {}).get("unmapped"),
                               "wall_ms": verify_ms})
        if candidate:
            last_status = verify.outcome
        if verify.outcome == "PASS" and verify.complete:
            result.accepted = True
            result.ledger = evidence.property_ledger(verify.payload)
            result.evidence_sufficient = evidence.evidence_sufficient(verify.payload)
            break
        feedback = prompts.render_feedback(prompts.apply_feedback_mode(
            prompts.build_explore_feedback(
                verify, property_ids=property_ids, index=property_index,
                include_concir_loc=(feedback_mode == "nomap")),
            feedback_mode))
    return _finish_cell(result, arm="SKEL", requirements=requirements,
                        design=last_nonempty, design_path=last_path,
                        last_check_ok=last_check_ok, skel_status=last_status,
                        provider=provider, backend=backend, oracle=oracle,
                        workdir=workdir, rust_mode=rust_mode, call_budget=call_budget,
                        rust_when_unverified=rust_when_unverified,
                        feedback_mode=feedback_mode, property_ids=property_ids,
                        compile_fn=compile_fn, tools=tools)


def run_cir_cell(*, task: str, requirements: str, contract_path: Path,
                 provider: CandidateProvider, backend: Any, oracle: Any,
                 workdir: Path, rounds: int = 4, replicate: int = 0,
                 rust_mode: str = "llm", call_budget: int = 5,
                 rust_when_unverified: str = "last", feedback_mode: str = "full",
                 property_ids: str = "keep", compile_fn=None,
                 tools=None) -> CellResult:
    result = CellResult(arm="CIR", task=task, replicate=replicate, rust_mode=rust_mode)
    feedback: str | None = None
    candidate: str | None = None
    last_nonempty: str | None = None
    last_path: Path | None = None
    last_check_ok = False
    last_status: str | None = None
    property_index: dict[str, str] = {}
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    attempts = max(1, min(rounds, call_budget - 1))
    for attempt in range(1, attempts + 1):
        result.rounds_used = attempt
        response = provider.propose(CandidateRequest(
            requirements=requirements, contract=None, feedback=feedback,
            attempt=attempt, previous_candidate=candidate, stage="cir"))
        if response.error:
            result.error = response.error
            break
        candidate = extract_cir(response.text)
        result.candidate = candidate
        cir_path = workdir / f"candidate_{attempt}.cir.json"
        # CIR is never normalised: the backend sees the extracted bytes as-is.
        cir_path.write_text(candidate, encoding="utf-8")
        started = time.monotonic()
        verify = backend.verify_cir(cir_path, contract_path)
        verify_ms = _ms_since(started)
        ok = verify.kind == "semantic" and verify.outcome not in (
            "INVALID", "UNSUPPORTED")
        if attempt == 1:
            result.parse_ok = bool(candidate) and verify.kind == "semantic"
        if ok:
            result.check_ok = True
        if candidate:
            last_nonempty = candidate
            last_path = cir_path
            last_check_ok = ok
            last_status = verify.outcome
        result.history.append({"attempt": attempt, "stage": "verify",
                               "outcome": verify.outcome, "complete": verify.complete,
                               "wall_ms": verify_ms})
        if verify.outcome == "PASS" and verify.complete:
            result.accepted = True
            result.ledger = evidence.property_ledger(verify.payload)
            result.evidence_sufficient = evidence.evidence_sufficient(verify.payload)
            break
        feedback = prompts.render_feedback(prompts.apply_feedback_mode(
            prompts.build_cir_feedback(verify, contract=contract,
                                       property_ids=property_ids,
                                       index=property_index),
            feedback_mode))
    return _finish_cell(result, arm="CIR", requirements=requirements,
                        design=last_nonempty, design_path=last_path,
                        last_check_ok=last_check_ok, skel_status=last_status,
                        provider=provider, backend=backend, oracle=oracle,
                        workdir=workdir, rust_mode=rust_mode, call_budget=call_budget,
                        rust_when_unverified=rust_when_unverified,
                        feedback_mode=feedback_mode, property_ids=property_ids,
                        compile_fn=compile_fn, tools=tools)


def _finish_cell(result: CellResult, *, arm: str, requirements: str,
                 design: str | None, design_path: Path | None, last_check_ok: bool,
                 skel_status: str | None,
                 provider, backend, oracle, workdir, rust_mode, call_budget,
                 rust_when_unverified, feedback_mode, property_ids, compile_fn,
                 tools) -> CellResult:
    if compile_fn is None:
        from .rusttools.compile import compile_rust
        compile_fn = compile_rust
    if tools is None:
        from .rusttools.runner import ToolRunner
        tools = ToolRunner()
    skel_verified = result.accepted
    calls_used = result.rounds_used
    rust, trace, oracle_result, error, extra = _run_rust_stage(
        arm=arm, rust_mode=rust_mode, design=design, design_path=design_path,
        requirements=requirements, provider=provider, backend=backend, oracle=oracle,
        workdir=workdir, calls_used=calls_used, call_budget=call_budget,
        rust_when_unverified=rust_when_unverified, skel_verified=skel_verified,
        last_check_ok=last_check_ok, compile_fn=compile_fn, tools=tools,
        result=result)
    result.rust, result.cir_trace, result.oracle = rust, trace, oracle_result
    if error and not result.error:
        result.error = error
    result.accepted = skel_verified and bool(extra["rust_compiled"])
    if rust_mode == "llm":
        extra["skel_status"] = skel_status if design is not None else "no_candidate"
    extra["feedback_mode"] = feedback_mode
    extra["property_ids"] = property_ids
    result.extra = extra
    return result


def run_g0_cell(*, task: str, requirements: str, provider: CandidateProvider,
                oracle: Any, workdir: Path, replicate: int = 0,
                compile_fn=None, tools=None) -> CellResult:
    """One-shot Rust. ``accepted`` is "this version compiles", not the oracle."""
    result = CellResult(arm="G0", task=task, replicate=replicate, rust_mode="llm")
    result.rounds_used = 1
    response = provider.propose(CandidateRequest(
        requirements=requirements, contract=None, feedback=None,
        attempt=1, stage="rust"))
    if response.error:
        result.error = response.error
        return result
    result.candidate = extract_rust(response.text)
    result.parse_ok = bool(result.candidate)
    result.rust = result.candidate
    from .rusttools.compile import compile_rust
    from .rusttools.runner import ToolRunner
    if compile_fn is None:
        compile_fn = compile_rust
    if tools is None:
        tools = ToolRunner()
    compiled = compile_fn(tools, Path(workdir) / "compile" / "c1", result.rust or "")
    result.extra["compile_wall_ms"] = getattr(compiled, "wall_ms", None)
    if getattr(compiled, "unavailable", None):
        result.check_ok = False
        result.accepted = False
        if not result.error:
            result.error = "compile_unavailable"
    elif getattr(compiled, "timed_out", False):
        result.check_ok = False
        result.accepted = False
        if not result.error:
            result.error = "compile_timeout"
    else:
        result.check_ok = bool(getattr(compiled, "ok", False))
        result.accepted = result.check_ok
    result.oracle = oracle.evaluate(result.rust or "", workdir)
    return result


def result_to_dict(result: CellResult) -> dict[str, Any]:
    out = {
        "arm": result.arm, "task": result.task, "replicate": result.replicate,
        "accepted": result.accepted, "error": result.error,
        "rust_mode": result.rust_mode,
        "parse_ok": result.parse_ok, "check_ok": result.check_ok,
        "rounds_used": result.rounds_used,
        "history": result.history, "ledger": result.ledger,
        "evidence_sufficient": result.evidence_sufficient,
        "oracle": None if result.oracle is None else oracle_result_dict(result.oracle),
    }
    for key, value in result.extra.items():
        if key in out:
            raise ValueError(f"CellResult.extra key {key!r} conflicts with a cell field")
        out[key] = value
    return out


def dumps(result: CellResult) -> str:
    return json.dumps(result_to_dict(result), ensure_ascii=False, indent=2)
