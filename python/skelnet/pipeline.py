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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import evidence, prompts
from .providers import CandidateProvider, CandidateRequest


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


def _extract_block(text: str, language: str) -> str:
    fence = f"```{language}"
    if fence in text:
        body = text.split(fence, 1)[1]
        return body.split("```", 1)[0].strip()
    if "```" in text:
        body = text.split("```", 1)[1]
        return body.split("```", 1)[0].strip()
    return text.strip()


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


def _skel_verify(backend, path: Path, contract_path: Path) -> Any:
    check = backend.check(path)
    if not check.ok:
        return check, None
    verify = backend.verify(path, contract_path)
    return check, verify


def _generate_rust(*, arm: str, rust_mode: str, accepted_path: Path, candidate: str,
                   requirements: str, provider: CandidateProvider, backend: Any,
                   oracle: Any, workdir: Path, attempt: int):
    """Produce final Rust and score it. Returns (rust, trace, oracle, error)."""
    if rust_mode == "codegen":
        if arm == "CIR":
            art = backend.codegen_cir(accepted_path, workdir / "codegen")
        else:
            art = backend.codegen_skel(accepted_path, workdir / "codegen")
        if not art.ok:
            return None, None, None, art.error
        extra = {"src/cir_trace.rs": art.trace_rs} if art.trace_rs else None
        return art.main_rs, art.trace_rs, oracle.evaluate(
            art.main_rs, workdir, extra_files=extra), None
    response = provider.propose(CandidateRequest(
        requirements=requirements, contract=None, feedback=None,
        attempt=attempt, previous_candidate=candidate, stage="rust"))
    if response.error:
        return None, None, None, response.error
    rust = extract_rust(response.text)
    return rust, None, oracle.evaluate(rust, workdir), None


def run_skel_cell(*, task: str, requirements: str, contract_path: Path,
                  provider: CandidateProvider, backend: Any, oracle: Any,
                  workdir: Path, rounds: int = 4, replicate: int = 0,
                  rust_mode: str = "llm") -> CellResult:
    result = CellResult(arm="SKEL", task=task, replicate=replicate, rust_mode=rust_mode)
    feedback: str | None = None
    candidate: str | None = None
    accepted_path: Path | None = None
    for attempt in range(1, rounds + 1):
        result.rounds_used = attempt
        response = provider.propose(CandidateRequest(
            requirements=requirements, contract=None, feedback=feedback,
            attempt=attempt, previous_candidate=candidate, stage="skel"))
        if response.error:
            result.error = response.error
            break
        candidate = extract_skel(response.text)
        result.candidate = candidate
        skel_path = workdir / f"candidate_{attempt}.skel"
        skel_path.write_text(candidate, encoding="utf-8")
        check, verify = _skel_verify(backend, skel_path, contract_path)
        if attempt == 1:
            result.parse_ok = bool(candidate) and check.kind == "semantic" and not _has_parse_error(check)
        if check.ok:
            result.check_ok = True
        if verify is None:
            feedback = prompts.render_feedback(prompts.build_check_feedback(check))
            result.history.append({"attempt": attempt, "stage": "check",
                                   "status": check.status,
                                   "diagnostics": (check.payload or {}).get("diagnostics")})
            continue
        result.history.append({"attempt": attempt, "stage": "verify",
                               "outcome": verify.outcome, "complete": verify.complete,
                               "unmapped": (verify.payload or {}).get("unmapped")})
        if verify.outcome == "PASS":
            result.accepted = True
            accepted_path = skel_path
            result.ledger = evidence.property_ledger(verify.payload)
            result.evidence_sufficient = evidence.evidence_sufficient(verify.payload)
            break
        feedback = prompts.render_feedback(prompts.build_explore_feedback(verify))

    if result.accepted and candidate is not None and accepted_path is not None:
        rust, trace, oracle_result, error = _generate_rust(
            arm="SKEL", rust_mode=rust_mode, accepted_path=accepted_path,
            candidate=candidate, requirements=requirements, provider=provider,
            backend=backend, oracle=oracle, workdir=workdir, attempt=rounds + 1)
        result.rust, result.cir_trace, result.oracle, result.error = rust, trace, oracle_result, error
    return result


def run_cir_cell(*, task: str, requirements: str, contract_path: Path,
                 provider: CandidateProvider, backend: Any, oracle: Any,
                 workdir: Path, rounds: int = 4, replicate: int = 0,
                 rust_mode: str = "llm") -> CellResult:
    result = CellResult(arm="CIR", task=task, replicate=replicate, rust_mode=rust_mode)
    feedback: str | None = None
    candidate: str | None = None
    accepted_path: Path | None = None
    for attempt in range(1, rounds + 1):
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
        cir_path.write_text(candidate, encoding="utf-8")
        verify = backend.verify_cir(cir_path, contract_path)
        if attempt == 1:
            result.parse_ok = bool(candidate) and verify.kind == "semantic"
            result.check_ok = result.parse_ok
        result.history.append({"attempt": attempt, "stage": "verify",
                               "outcome": verify.outcome, "complete": verify.complete})
        if verify.outcome == "PASS":
            result.accepted = True
            accepted_path = cir_path
            result.ledger = evidence.property_ledger(verify.payload)
            result.evidence_sufficient = evidence.evidence_sufficient(verify.payload)
            break
        feedback = prompts.render_feedback(prompts.build_cir_feedback(verify))

    if result.accepted and candidate is not None and accepted_path is not None:
        rust, trace, oracle_result, error = _generate_rust(
            arm="CIR", rust_mode=rust_mode, accepted_path=accepted_path,
            candidate=candidate, requirements=requirements, provider=provider,
            backend=backend, oracle=oracle, workdir=workdir, attempt=rounds + 1)
        result.rust, result.cir_trace, result.oracle, result.error = rust, trace, oracle_result, error
    return result


def run_g0_cell(*, task: str, requirements: str, provider: CandidateProvider,
                oracle: Any, workdir: Path, replicate: int = 0) -> CellResult:
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
    result.check_ok = result.parse_ok
    result.rust = result.candidate
    result.oracle = oracle.evaluate(result.rust, workdir)
    result.accepted = bool(getattr(result.oracle, "functional_ok", False))
    return result


def result_to_dict(result: CellResult) -> dict[str, Any]:
    return {
        "arm": result.arm, "task": result.task, "replicate": result.replicate,
        "accepted": result.accepted, "error": result.error,
        "rust_mode": result.rust_mode,
        "parse_ok": result.parse_ok, "check_ok": result.check_ok,
        "rounds_used": result.rounds_used,
        "history": result.history, "ledger": result.ledger,
        "evidence_sufficient": result.evidence_sufficient,
        "oracle": None if result.oracle is None else {
            "built": result.oracle.built, "ran": result.oracle.ran,
            "functional_ok": result.oracle.functional_ok,
            "terminal_check": getattr(result.oracle, "terminal_check", None),
        },
    }


def dumps(result: CellResult) -> str:
    return json.dumps(result_to_dict(result), ensure_ascii=False, indent=2)
