"""Prompt assets and structured verification feedback.

Feedback keeps the backend's actual property ids, mapped DSL positions,
counterexamples and preserved failures. It NEVER includes the contract's goal
formulas or the contract file (see ``docs/feedback.md``).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PROMPT_ASSET_DIR = Path(__file__).resolve().parents[2] / "prompts"

SKEL_GENERATION_ASSET = "skel_generation_v1.md"
SKEL_FEEDBACK_ASSET = "skel_feedback_v1.md"
RUST_FROM_SKEL_ASSET = "rust_from_skel_v1.md"
CIR_GENERATION_ASSET = "concir_generation_v4.md"
CIR_FEEDBACK_ASSET = "concir_feedback_v1.md"
RUST_FROM_CIR_ASSET = "rust_from_cir_v2.md"
RUST_GENERATION_ASSET = "rust_generation_v1.md"

ASSETS = (
    SKEL_GENERATION_ASSET, SKEL_FEEDBACK_ASSET, RUST_FROM_SKEL_ASSET,
    CIR_GENERATION_ASSET, CIR_FEEDBACK_ASSET, RUST_FROM_CIR_ASSET,
    RUST_GENERATION_ASSET,
)

# Explicit arm x stage -> system-prompt asset. A missing route is an error; the
# workflow never silently falls back to another arm's prompt.
STAGE_GENERATE = "generate"
STAGE_FEEDBACK = "feedback"
STAGE_RUST = "rust"

PROMPT_ROUTES: dict[tuple[str, str], str] = {
    ("SKEL", STAGE_GENERATE): SKEL_GENERATION_ASSET,
    ("SKEL", STAGE_FEEDBACK): SKEL_FEEDBACK_ASSET,
    ("SKEL", STAGE_RUST): RUST_FROM_SKEL_ASSET,
    ("CIR", STAGE_GENERATE): CIR_GENERATION_ASSET,
    ("CIR", STAGE_FEEDBACK): CIR_FEEDBACK_ASSET,
    ("CIR", STAGE_RUST): RUST_FROM_CIR_ASSET,
    ("G0", STAGE_GENERATE): RUST_GENERATION_ASSET,
}


def route(arm: str, stage: str) -> str:
    """Return the system-prompt asset for an arm x stage, or raise."""
    key = (arm, stage)
    if key not in PROMPT_ROUTES:
        raise KeyError(
            f"no system-prompt route for arm={arm!r} stage={stage!r}; "
            f"known routes: {sorted(PROMPT_ROUTES)}")
    return PROMPT_ROUTES[key]


def system_prompt_for(arm: str, stage: str) -> str:
    """Read the routed system prompt (raises on an unmapped arm x stage)."""
    return read_asset(route(arm, stage))


def routes_for_arm(arm: str) -> dict[str, str]:
    """The `{stage: asset}` map for one arm (used by `--dry-run`)."""
    return {stage: asset for (a, stage), asset in PROMPT_ROUTES.items() if a == arm}


def read_asset(name: str) -> str:
    return (PROMPT_ASSET_DIR / name).read_text(encoding="utf-8")


def prompt_asset_record() -> dict[str, str]:
    out: dict[str, str] = {}
    for name in ASSETS:
        path = PROMPT_ASSET_DIR / name
        if path.exists():
            out[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def skel_generation_system_prompt() -> str:
    return read_asset(SKEL_GENERATION_ASSET)


def skel_feedback_system_prompt() -> str:
    return read_asset(SKEL_FEEDBACK_ASSET)


def rust_from_skel_system_prompt() -> str:
    return read_asset(RUST_FROM_SKEL_ASSET)


def cir_generation_system_prompt() -> str:
    return read_asset(CIR_GENERATION_ASSET)


def rust_from_cir_system_prompt() -> str:
    return read_asset(RUST_FROM_CIR_ASSET)


def rust_generation_system_prompt() -> str:
    return read_asset(RUST_GENERATION_ASSET)


def requirements_only_user_prompt(requirements: str, *,
                                  previous_candidate: str | None = None,
                                  feedback: str | None = None) -> str:
    """Generation user prompt that never contains the verification contract."""
    parts = [
        "Produce one answer for the requirements below. No verification "
        "contract is provided; the requirements are the whole input.",
        "",
        "<domain_requirements>",
        requirements.strip(),
        "</domain_requirements>",
    ]
    if previous_candidate:
        parts += ["", "<previous_candidate>", previous_candidate, "</previous_candidate>"]
    if feedback:
        parts += ["", "<verification_feedback>", feedback, "</verification_feedback>",
                  "Output the complete corrected artifact."]
    return "\n".join(parts)


def rust_from_skel_user_prompt(requirements: str, skeleton: str) -> str:
    return (
        "Write a single-file std-only Rust program implementing the skeleton "
        "below. Use the skeleton's resource and function names as Rust "
        "identifiers, `lock m {}` as a guard scope, `permit` as a `Permit`, "
        "`post`/`take` via `concir_sync`, and keep `// @Rn` comments.\n\n"
        "<domain_requirements>\n" + requirements.strip() + "\n</domain_requirements>\n\n"
        "<skeleton>\n" + skeleton.strip() + "\n</skeleton>\n\n"
        "Output only one ```rust code block."
    )


def rust_from_cir_user_prompt(requirements: str, cir: str) -> str:
    return (
        "Write a single-file std-only Rust program implementing the verified "
        "ConcIR program below. Use the program's resource and function names as "
        "Rust identifiers, `mutex_lock`/`mutex_unlock` as a guard scope, "
        "semaphore acquire/release via `concir_sync`, and keep `// @cir <sid>` "
        "comments.\n\n"
        "<domain_requirements>\n" + requirements.strip() + "\n</domain_requirements>\n\n"
        "<concir>\n" + cir.strip() + "\n</concir>\n\n"
        "Output only one ```rust code block."
    )


def build_check_feedback(result) -> dict[str, Any]:
    payload = result.payload or {}
    return {
        "stage": "check",
        "status": result.status,
        "valid": payload.get("valid"),
        "unmapped": payload.get("unmapped"),
        "validation_diagnostics": payload.get("diagnostics", []) or [],
        "support_error": payload.get("support_error"),
        "process_error": result.error if result.kind != "semantic" else None,
    }


def build_explore_feedback(result, *, preserved_ids: list[str] | None = None) -> dict[str, Any]:
    """Disclosure-safe verification feedback (no contract goal, ever)."""
    payload = result.payload or {}
    properties = payload.get("properties", []) or []
    failed = [
        {"id": p.get("id"), "outcome": p.get("outcome"), "detail": p.get("detail"),
         "reqs": p.get("reqs")}
        for p in properties if p.get("outcome") not in (None, "PASS")
    ]
    preserved_unmet = [p for p in failed if str(p.get("id", "")).startswith("preserved:")]
    diagnostics = []
    for d in payload.get("diagnostics", []) or []:
        diagnostics.append({
            "property": d.get("code") or d.get("property"),
            "outcome": d.get("severity"),
            "message": d.get("message"),
            "skel": d.get("skel"),
            "unmapped": d.get("unmapped"),
        })
    counterexamples = []
    for ce in payload.get("counterexamples", []) or []:
        counterexamples.append({
            "property": ce.get("property"),
            "reqs": ce.get("reqs"),
            "steps": [
                {"step": s.get("step"), "thread": s.get("thread"),
                 "function": s.get("function"), "line": (s.get("skel") or {}).get("line"),
                 "statement": s.get("statement")}
                for s in ce.get("steps", [])
            ],
            "final_note": ce.get("final_note"),
        })
    return {
        "stage": "explore",
        "outcome": result.outcome,
        "complete": result.complete,
        "failed_properties": failed,
        "preserved_unmet": preserved_unmet,
        "diagnostics": diagnostics,
        "counterexamples": counterexamples,
        "unmapped": payload.get("unmapped"),
        "note": ("UNKNOWN means the analysis did not complete; it is not a proof "
                 "of safety. FAIL may already contain a counterexample."),
    }


def render_feedback(feedback: dict[str, Any]) -> str:
    return json.dumps(feedback, ensure_ascii=False, indent=2)
