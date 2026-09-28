"""Prompt assets and structured verification feedback.

Feedback keeps the backend's actual property ids, mapped DSL positions,
counterexamples and preserved failures. It NEVER includes the contract's goal
formulas or the contract file (see ``docs/feedback.md``).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

PROMPT_ASSET_DIR = Path(__file__).resolve().parents[2] / "prompts"

SKEL_GENERATION_ASSET = "skel_generation_v1.md"
SKEL_FEEDBACK_ASSET = "skel_feedback_v1.md"
RUST_FROM_SKEL_ASSET = "rust_from_skel_v1.md"
RUST_FROM_SKEL_V2_ASSET = "rust_from_skel_v2.md"
CIR_GENERATION_ASSET = "concir_generation_v4.md"
CIR_FEEDBACK_ASSET = "concir_feedback_v1.md"
RUST_FROM_CIR_ASSET = "rust_from_cir_v2.md"
RUST_FROM_CIR_V3_ASSET = "rust_from_cir_v3.md"
RUST_GENERATION_ASSET = "rust_generation_v1.md"
RUST_GENERATION_V2_ASSET = "rust_generation_v2.md"
RUST_RUNTIME_API_ASSET = "rust_runtime_api_v1.md"
RUST_COMPILE_FIX_ASSET = "rust_compile_fix_v1.md"

ASSETS = (
    SKEL_GENERATION_ASSET, SKEL_FEEDBACK_ASSET, RUST_FROM_SKEL_ASSET,
    RUST_FROM_SKEL_V2_ASSET, CIR_GENERATION_ASSET, CIR_FEEDBACK_ASSET,
    RUST_FROM_CIR_ASSET, RUST_FROM_CIR_V3_ASSET,
    RUST_GENERATION_ASSET, RUST_GENERATION_V2_ASSET, RUST_RUNTIME_API_ASSET,
    RUST_COMPILE_FIX_ASSET,
)

# Explicit arm x stage -> ordered system-prompt assets. A missing route is an
# error; the workflow never silently falls back to another arm's prompt. A
# feedback stage carries the generation template first (the model still needs
# the DSL grammar / ConcIR schema), then the feedback-reading template.
STAGE_GENERATE = "generate"
STAGE_FEEDBACK = "feedback"
STAGE_RUST = "rust"
STAGE_RUST_FIX = "rust_fix"

# Fixed separator used when concatenating an ordered template tuple.
PROMPT_SEPARATOR = "\n\n---\n\n"

PROMPT_ROUTES: dict[tuple[str, str], tuple[str, ...]] = {
    ("SKEL", STAGE_GENERATE): (SKEL_GENERATION_ASSET,),
    ("SKEL", STAGE_FEEDBACK): (SKEL_GENERATION_ASSET, SKEL_FEEDBACK_ASSET),
    ("SKEL", STAGE_RUST): (RUST_FROM_SKEL_V2_ASSET, RUST_RUNTIME_API_ASSET),
    ("SKEL", STAGE_RUST_FIX): (RUST_COMPILE_FIX_ASSET, RUST_RUNTIME_API_ASSET),
    ("CIR", STAGE_GENERATE): (CIR_GENERATION_ASSET,),
    ("CIR", STAGE_FEEDBACK): (CIR_GENERATION_ASSET, CIR_FEEDBACK_ASSET),
    ("CIR", STAGE_RUST): (RUST_FROM_CIR_V3_ASSET, RUST_RUNTIME_API_ASSET),
    ("CIR", STAGE_RUST_FIX): (RUST_COMPILE_FIX_ASSET, RUST_RUNTIME_API_ASSET),
    ("G0", STAGE_GENERATE): (RUST_GENERATION_V2_ASSET, RUST_RUNTIME_API_ASSET),
}

# Appended to the feedback of a Rust-stage retry when the model did not return a
# usable program. REFINE-style arms may additionally answer NO_ISSUES.
FORMAT_RETRY_NOTE = (
    "Your previous reply did not contain a complete program inside a single "
    "```rust code block. Reply again with exactly one ```rust code block "
    "containing the whole program (or, if the program has no issues, the exact "
    "word NO_ISSUES)."
)

# ── baseline arms (round 4) ──────────────────────────────────────────
# ``generate`` matches G0 byte for byte. ``rust_fix`` matches the SKEL/CIR
# compile-fix route (``STAGE_RUST_FIX``).
RUST_SELF_REFINE_ASSET = "rust_self_refine_v1.md"
RUST_STATIC_FEEDBACK_ASSET = "rust_static_feedback_v1.md"
RUST_DYNAMIC_FEEDBACK_ASSET = "rust_dynamic_feedback_v1.md"
RUST_DYNAMIC_MONITOR_FEEDBACK_ASSET = "rust_dynamic_monitor_feedback_v1.md"

BASELINE_ASSETS = (
    RUST_SELF_REFINE_ASSET, RUST_STATIC_FEEDBACK_ASSET,
    RUST_DYNAMIC_FEEDBACK_ASSET, RUST_DYNAMIC_MONITOR_FEEDBACK_ASSET,
)
ASSETS = ASSETS + BASELINE_ASSETS

BASELINE_ARMS = ("REFINE", "STATIC", "DYNAMIC", "DYNAMIC_M")
STAGE_REVIEW = "review"
STAGE_TOOL_FEEDBACK = "tool_feedback"

BASELINE_ROUTES: dict[tuple[str, str], tuple[str, ...]] = {}
for _arm in BASELINE_ARMS:
    BASELINE_ROUTES[(_arm, STAGE_GENERATE)] = (
        RUST_GENERATION_V2_ASSET, RUST_RUNTIME_API_ASSET)
    BASELINE_ROUTES[(_arm, STAGE_RUST_FIX)] = (
        RUST_COMPILE_FIX_ASSET, RUST_RUNTIME_API_ASSET)
BASELINE_ROUTES[("REFINE", STAGE_REVIEW)] = (
    RUST_SELF_REFINE_ASSET, RUST_RUNTIME_API_ASSET)
BASELINE_ROUTES[("STATIC", STAGE_TOOL_FEEDBACK)] = (
    RUST_STATIC_FEEDBACK_ASSET, RUST_RUNTIME_API_ASSET)
BASELINE_ROUTES[("DYNAMIC", STAGE_TOOL_FEEDBACK)] = (
    RUST_DYNAMIC_FEEDBACK_ASSET, RUST_RUNTIME_API_ASSET)
BASELINE_ROUTES[("DYNAMIC_M", STAGE_TOOL_FEEDBACK)] = (
    RUST_DYNAMIC_MONITOR_FEEDBACK_ASSET, RUST_RUNTIME_API_ASSET)
PROMPT_ROUTES.update(BASELINE_ROUTES)


def route(arm: str, stage: str) -> tuple[str, ...]:
    """Return the ordered system-prompt assets for an arm x stage, or raise."""
    key = (arm, stage)
    if key not in PROMPT_ROUTES:
        raise KeyError(
            f"no system-prompt route for arm={arm!r} stage={stage!r}; "
            f"known routes: {sorted(PROMPT_ROUTES)}")
    return PROMPT_ROUTES[key]


def system_prompt_for(arm: str, stage: str) -> str:
    """Read and concatenate the routed system prompt (raises if unmapped)."""
    return PROMPT_SEPARATOR.join(read_asset(a) for a in route(arm, stage))


def routes_for_arm(arm: str) -> dict[str, tuple[str, ...]]:
    """The `{stage: assets}` map for one arm (used by `--dry-run`)."""
    return {stage: assets for (a, stage), assets in PROMPT_ROUTES.items() if a == arm}


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


def rust_from_skel_user_prompt(requirements: str, skeleton: str, *,
                               retry_note: str | None = None) -> str:
    note = (retry_note.strip() + "\n\n") if retry_note else ""
    return (
        "Write a single-file std-only Rust program implementing the skeleton "
        "below. Use the skeleton's resource and function names as Rust "
        "identifiers, `lock m {}` as a guard scope, `permit` as a `Permit`, "
        "`post`/`take` via `concir_sync`, and keep `// @Rn` comments.\n\n"
        "<domain_requirements>\n" + requirements.strip() + "\n</domain_requirements>\n\n"
        "<skeleton>\n" + skeleton.strip() + "\n</skeleton>\n\n"
        + note +
        "Output only one ```rust code block."
    )


def rust_from_cir_user_prompt(requirements: str, cir: str, *,
                              retry_note: str | None = None) -> str:
    note = (retry_note.strip() + "\n\n") if retry_note else ""
    return (
        "Write a single-file std-only Rust program implementing the ConcIR "
        "program below. Use the program's resource and function names as "
        "Rust identifiers, `mutex_lock`/`mutex_unlock` as a guard scope, "
        "semaphore acquire/release via `concir_sync`, and keep `// @cir <sid>` "
        "comments.\n\n"
        "<domain_requirements>\n" + requirements.strip() + "\n</domain_requirements>\n\n"
        "<concir>\n" + cir.strip() + "\n</concir>\n\n"
        + note +
        "Output only one ```rust code block."
    )


def rust_compile_fix_user_prompt(requirements: str, program: str, diagnostics: str,
                                 *, design: str | None = None,
                                 design_kind: str | None = None) -> str:
    """User prompt for a Rust-stage compile retry (all arms)."""
    parts = [
        "The Rust program below does not compile. Fix it so `cargo build` "
        "succeeds, keeping the required behaviour.",
        "",
        "<domain_requirements>",
        requirements.strip(),
        "</domain_requirements>",
        "",
        "<previous_program>",
        program.strip(),
        "</previous_program>",
        "",
        "<rustc_diagnostics>",
        diagnostics.strip(),
        "</rustc_diagnostics>",
    ]
    if design:
        tag = "concir" if design_kind == "cir" else "skeleton"
        parts += ["", f"<{tag}>", design.strip(), f"</{tag}>"]
    parts += ["", "Output only one ```rust code block."]
    return "\n".join(parts)


def present_property_id(pid: str, policy: str, index: dict[str, str]) -> str:
    """Map a property id to what the model sees (``keep`` or opaque ``P<n>``).

    ``index`` is owned by the caller and keeps one cell's mapping stable.
    """
    if policy == "keep":
        return pid
    if pid not in index:
        index[pid] = f"P{len(index) + 1}"
    return index[pid]


# ── disclosure sanitisation (shared by the SKEL and CIR feedback builders) ──

PRESERVED_DETAIL = "preserved behaviour is not reachable in any explored schedule"
REDACTED_DETAIL = "property is not reachable in any explored schedule"

# Substrings that betray a contract goal formula in a property `detail`.
_GOAL_MARKERS = ("holds_all(", "completed(", "function_completed", "goal")

# A process error such as "JSON parse error in '/abs/path.json': ..." must not
# leak the file path.
_PROCESS_PATH_RE = re.compile(r"\s+in '[^']*':\s*")


def sanitize_detail(pid: Any, detail: Any) -> Any:
    """Replace goal-revealing `detail` text; keep the id/outcome untouched."""
    if detail is None:
        return None
    text = str(detail)
    if str(pid or "").startswith("preserved:"):
        return PRESERVED_DETAIL
    if any(marker in text for marker in _GOAL_MARKERS):
        return REDACTED_DETAIL
    return detail


def sanitize_process_error(error: str | None) -> str | None:
    """Drop the file path from a backend process error."""
    if not error:
        return error
    return _PROCESS_PATH_RE.sub(": ", error, count=1)


def _failed_properties(payload: dict[str, Any]) -> list[dict[str, Any]]:
    properties = payload.get("properties", []) or []
    failed = []
    for p in properties:
        if p.get("outcome") in (None, "PASS"):
            continue
        pid = p.get("id")
        failed.append({
            "id": pid,
            "outcome": p.get("outcome"),
            "detail": sanitize_detail(pid, p.get("detail")),
            "reqs": p.get("reqs"),
        })
    return failed


def build_check_feedback(result, *, property_ids: str = "keep",
                         index: dict[str, str] | None = None) -> dict[str, Any]:
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


def _normalize_id(pid: Any) -> Any:
    """Drop a backend ``property:`` prefix so one property has one number."""
    if isinstance(pid, str) and pid.startswith("property:"):
        return pid[len("property:"):]
    return pid


def _register_and_show(ids, property_ids: str, index: dict[str, str]):
    for pid in ids:
        if pid:
            present_property_id(_normalize_id(pid), property_ids, index)

    def show(pid):
        return present_property_id(_normalize_id(pid), property_ids, index) if pid else pid

    def show_text(text):
        if property_ids == "keep" or not text:
            return text
        replacements: dict[str, str] = {}
        for original, shown in index.items():
            replacements[original] = shown
            if original.startswith("preserved: "):
                # Free text carries the bare description, not the prefix.
                replacements[original[len("preserved: "):]] = shown
        for original in sorted(replacements, key=len, reverse=True):
            text = text.replace(original, replacements[original])
        return text

    return show, show_text


def build_explore_feedback(result, *, preserved_ids: list[str] | None = None,
                           property_ids: str = "keep",
                           index: dict[str, str] | None = None,
                           include_concir_loc: bool = False) -> dict[str, Any]:
    """Disclosure-safe verification feedback (no contract goal, ever).

    ``include_concir_loc`` adds the raw ConcIR location to diagnostics/steps; it
    is only opened for ``nomap`` (the other modes keep the 9dfaefe field sets).
    """
    payload = result.payload or {}
    index = index if index is not None else {}
    # `detail` is sanitized (preserved goals are replaced) by the shared helper.
    failed = _failed_properties(payload)
    preserved_unmet = [p for p in failed if str(p.get("id", "")).startswith("preserved:")]
    raw_counterexamples = payload.get("counterexamples", []) or []
    raw_diagnostics = payload.get("diagnostics", []) or []
    ids = ([p.get("id") for p in failed]
           + [ce.get("property") for ce in raw_counterexamples]
           + [(d.get("code") or d.get("property")) for d in raw_diagnostics])
    show, show_text = _register_and_show(ids, property_ids, index)
    for entry in failed:
        entry["id"] = show(entry["id"])
        entry["detail"] = show_text(entry["detail"])
    diagnostics = []
    for d in raw_diagnostics:
        item = {
            "property": show(d.get("code") or d.get("property")),
            "outcome": d.get("severity"),
            "message": show_text(d.get("message")),
            "skel": d.get("skel"),
            "unmapped": d.get("unmapped"),
        }
        if include_concir_loc:
            item["concir_loc"] = (d.get("skel") or {}).get("loc")
        diagnostics.append(item)
    counterexamples = []
    for ce in raw_counterexamples:
        steps = []
        for s in ce.get("steps", []):
            step = {"step": s.get("step"), "thread": s.get("thread"),
                    "function": s.get("function"),
                    "line": (s.get("skel") or {}).get("line"),
                    "statement": s.get("statement")}
            if include_concir_loc:
                step["concir_loc"] = (s.get("skel") or {}).get("loc")
            steps.append(step)
        counterexamples.append({
            "property": show(ce.get("property")),
            "reqs": ce.get("reqs"),
            "steps": steps,
            "final_note": show_text(ce.get("final_note")),
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


def _contract_reqs(contract: dict | None) -> dict[str, Any]:
    """Property id -> requirement ids, from the contract's `req` field only."""
    mapping: dict[str, Any] = {}
    if not isinstance(contract, dict):
        return mapping
    for prop in contract.get("properties") or []:
        if isinstance(prop, dict) and isinstance(prop.get("id"), str):
            mapping[prop["id"]] = prop.get("req")
    for prop in contract.get("preserved") or []:
        if isinstance(prop, dict) and isinstance(prop.get("description"), str):
            mapping[f"preserved: {prop['description']}"] = prop.get("req")
    return mapping


def build_cir_feedback(result, *, contract: dict | None = None,
                       property_ids: str = "keep",
                       index: dict[str, str] | None = None) -> dict[str, Any]:
    """Disclosure-safe feedback from ``concir-backend explore`` (CIR arm).

    The CIR backend output has a different shape from the skeleton feedback:
    JSON-parse failures are process errors, static errors are in ``invalid[]``,
    and counterexamples live in ``diagnostics[].counterexample_names`` /
    ``doom_state``. Aligned with ``concir_feedback_v1.md``; never includes
    ``repair_hints``, ``proven_facts``, contract fingerprints, bounds, or any
    contract field except the requirement ids.
    """
    payload = result.payload or {}
    index = index if index is not None else {}
    process_error = None
    if result.kind != "semantic":
        process_error = sanitize_process_error(result.error)

    diagnostics = [
        {"code": inv.get("code"), "location": inv.get("location"),
         "message": inv.get("message")}
        for inv in payload.get("invalid", []) or []
    ]

    failed = _failed_properties(payload)
    preserved_unmet = [p for p in failed if str(p.get("id", "")).startswith("preserved:")]
    raw_counterexamples = payload.get("diagnostics", []) or []
    ids = ([p.get("id") for p in failed]
           + [d.get("property") for d in raw_counterexamples])
    # Fill reqs from the contract with the ORIGINAL ids, before they are opaque.
    reqs = _contract_reqs(contract)
    for entry in failed:
        if entry.get("reqs") is None and entry.get("id") in reqs:
            entry["reqs"] = reqs[entry["id"]]
    show, show_text = _register_and_show(ids, property_ids, index)
    for entry in failed:
        entry["id"] = show(entry["id"])
        entry["detail"] = show_text(entry["detail"])

    counterexamples = []
    for d in raw_counterexamples:
        names = d.get("counterexample_names") or []
        if not names:
            continue
        final_state = [
            {"function": t.get("function"), "at_sid": t.get("at_sid"),
             "holds": t.get("holds"), "waiting_on": t.get("waiting_on")}
            for t in (d.get("doom_state") or {}).get("threads", []) or []
        ]
        counterexamples.append({
            "property": show(d.get("property")),
            "message": show_text(d.get("message")),
            "steps": list(names),
            "final_state": final_state,
        })

    return {
        "stage": "explore",
        "outcome": result.outcome,
        "complete": result.complete,
        "process_error": process_error,
        "diagnostics": diagnostics,
        "failed_properties": failed,
        "preserved_unmet": preserved_unmet,
        "counterexamples": counterexamples,
    }


def apply_feedback_mode(feedback: dict[str, Any], mode: str) -> dict[str, Any]:
    """Trim a verification-stage feedback dict according to ``feedback_mode``.

    - ``full``: unchanged.
    - ``outcome_only``: keep only ``stage``/``outcome``/``complete`` and the
      failed property ids (the check stage is never trimmed).
    - ``nocex``: drop ``counterexamples``; everything else unchanged.
    - ``nomap``: drop the mapped DSL positions (``line``/``col``/``skel``/
      ``statement``) and keep only the raw ConcIR location.
    """
    if mode == "full":
        return feedback
    out = dict(feedback)
    if mode == "outcome_only":
        keep = {key: out[key] for key in ("stage", "outcome", "complete")
                if key in out}
        keep["failed_properties"] = [{"id": p.get("id")}
                                     for p in out.get("failed_properties") or []]
        keep["preserved_unmet"] = [{"id": p.get("id")}
                                   for p in out.get("preserved_unmet") or []]
        return keep
    if mode == "nocex":
        out.pop("counterexamples", None)
        return out
    if mode == "nomap":
        out["diagnostics"] = [
            {k: v for k, v in d.items() if k not in ("skel", "line", "col")}
            for d in out.get("diagnostics") or []
        ]
        out["counterexamples"] = [
            {**ce, "steps": [
                {k: v for k, v in s.items()
                 if k not in ("line", "col", "statement")}
                for s in ce.get("steps") or []
            ]}
            for ce in out.get("counterexamples") or []
        ]
        return out
    return feedback


def render_feedback(feedback: dict[str, Any]) -> str:
    return json.dumps(feedback, ensure_ascii=False, indent=2)


def baseline_review_user_prompt(requirements: str, program: str, *,
                                feedback: str | None = None) -> str:
    """REFINE review turn: the current program, plus an optional format note."""
    parts = [
        "Review the program for concurrency defects. If you find one, output a "
        "corrected program. If you are sure there is none, reply with exactly "
        "NO_ISSUES.",
        "",
        "<domain_requirements>",
        requirements.strip(),
        "</domain_requirements>",
        "",
        "<current_program>",
        program.strip(),
        "</current_program>",
    ]
    if feedback:
        parts += ["", feedback.strip()]
    parts += ["", "Output one ```rust code block, or exactly NO_ISSUES."]
    return "\n".join(parts)


def baseline_tool_feedback_user_prompt(requirements: str, program: str,
                                       feedback: str, *, source: str) -> str:
    """STATIC / DYNAMIC / DYNAMIC_M tool-feedback turn.

    ``source`` is ``static``, ``dynamic``, or ``dynamic_monitor``.
    """
    parts = [
        "The program compiled. The tool feedback below is the reason it was "
        "not accepted. Correct the program.",
        "",
        "<domain_requirements>",
        requirements.strip(),
        "</domain_requirements>",
        "",
        "<current_program>",
        program.strip(),
        "</current_program>",
        "",
        f'<tool_feedback source="{source}">',
        feedback.strip(),
        "</tool_feedback>",
        "",
        "Output one ```rust code block.",
    ]
    return "\n".join(parts)
