"""R9d-P2: the SKEL/CIR Rust prompts carry the same policy rules as G0.

`rust_from_skel_v3.md` and `rust_from_cir_v4.md` add the O1 policy rules, the
`scope` -> `std::thread::spawn` + `join` translation (no `thread::scope`) and
the busy-wait rule. The rule table asserts the three generation prompts agree on
the shared policy and that the skeleton prompts are not less strict than G0.
"""

import re
from pathlib import Path

from skelnet import prompts

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"

G0 = PROMPT_DIR / "rust_generation_v2.md"
SKEL = PROMPT_DIR / "rust_from_skel_v3.md"
CIR = PROMPT_DIR / "rust_from_cir_v4.md"

# rule -> (regex, arms that must state it). "all" = every Rust-stage prompt.
# The effective prompt is the generation asset plus the shared runtime appendix,
# so the `scope` rule (now in rust_runtime_api_v2.md) applies to every arm.
RULES = {
    "no_other_crates": (r"(no\s+other\s+crates|No external crates|only the standard "
                        r"library)", "all"),
    "no_unsafe": (r"no\s+`?unsafe", "all"),
    "no_feature": (r"#!\[feature\]", "all"),
    "no_sleep_yield": (r"(sleep.*yield_now|yield_now.*sleep|sleep.{0,40}yield_now)",
                       "all"),
    "no_thread_scope": (r"thread::scope", "all"),
    "no_static_mut": (r"static mut", ("SKEL", "CIR")),
    "no_extern_crate": (r"extern crate", ("SKEL", "CIR")),
    "no_process_exit_abort": (r"process::exit", ("SKEL", "CIR")),
    "busy_wait": (r"busy[- ]wait", ("SKEL", "CIR")),
}

RUNTIME_V1 = "rust_runtime_api_v1.md"
RUNTIME_V2 = "rust_runtime_api_v2.md"

# The two DYNAMIC tool-feedback prompts describe the tools whose output they
# carry; they are existing files and the only allowed judge-word exceptions.
JUDGE_WORDS = re.compile(r"explorer|shuttle|oracle|schedule|builder",
                         re.IGNORECASE)
JUDGE_EXCEPTIONS = {"rust_dynamic_feedback_v1.md",
                    "rust_dynamic_monitor_feedback_v1.md"}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_routes_point_at_new_assets():
    assert prompts.route("SKEL", prompts.STAGE_RUST) == (
        "rust_from_skel_v3.md", "rust_runtime_api_v2.md")
    assert prompts.route("CIR", prompts.STAGE_RUST) == (
        "rust_from_cir_v4.md", "rust_runtime_api_v2.md")


def test_old_prompt_files_are_kept():
    assert (PROMPT_DIR / "rust_from_skel_v2.md").is_file()
    assert (PROMPT_DIR / "rust_from_cir_v3.md").is_file()


def _composed(assets) -> str:
    return prompts.PROMPT_SEPARATOR.join(prompts.read_asset(a) for a in assets)


# The effective Rust-stage system prompt per arm (generation asset + appendix).
ROUTES = {
    "G0": prompts.route("G0", prompts.STAGE_GENERATE),
    "SKEL": prompts.route("SKEL", prompts.STAGE_RUST),
    "CIR": prompts.route("CIR", prompts.STAGE_RUST),
}


def test_rule_table_across_generation_prompts():
    texts = {arm: _composed(assets) for arm, assets in ROUTES.items()}
    for rule, (pattern, required) in RULES.items():
        targets = list(texts) if required == "all" else list(required)
        for target in targets:
            assert re.search(pattern, texts[target], re.IGNORECASE), \
                f"{rule} missing from arm {target}"


def _is_skeleton_route(key) -> bool:
    arm, stage = key
    return arm in ("SKEL", "CIR") and stage in (prompts.STAGE_GENERATE,
                                                prompts.STAGE_FEEDBACK)


def test_every_rust_route_uses_runtime_v2():
    routes = {k: v for k, v in prompts.PROMPT_ROUTES.items()
              if not _is_skeleton_route(k)}
    assert len(routes) == 17, sorted(routes)
    for (arm, stage), assets in routes.items():
        assert RUNTIME_V2 in assets, (arm, stage, assets)
        assert RUNTIME_V1 not in assets, (arm, stage, assets)


def test_skeleton_and_concir_routes_have_no_runtime_appendix():
    routes = {k: v for k, v in prompts.PROMPT_ROUTES.items()
              if _is_skeleton_route(k)}
    assert len(routes) == 4, sorted(routes)
    for assets in routes.values():
        assert RUNTIME_V1 not in assets and RUNTIME_V2 not in assets


def test_no_judge_tool_words_in_routed_assets():
    assets = sorted({a for v in prompts.PROMPT_ROUTES.values() for a in v})
    hits = {}
    for asset in assets:
        if asset in JUDGE_EXCEPTIONS:
            continue
        text = (PROMPT_DIR / asset).read_text(encoding="utf-8")
        match = JUDGE_WORDS.search(text)
        if match:
            hits[asset] = match.group(0)
    assert hits == {}, hits
    # Both documented exceptions must actually be routed.
    assert JUDGE_EXCEPTIONS <= set(assets)


def test_runtime_v2_forbids_thread_scope():
    text = _text(PROMPT_DIR / RUNTIME_V2)
    assert "std::thread::spawn" in text
    assert re.search(r"Do not use `std::thread::scope`", text), text


def test_skel_cir_are_not_less_strict_than_g0():
    # Every shared rule must appear in all three effective prompts.
    texts = {arm: _composed(assets) for arm, assets in ROUTES.items()}
    for rule, (pattern, _required) in RULES.items():
        if not re.search(pattern, texts["G0"], re.IGNORECASE):
            continue
        for arm in ("SKEL", "CIR"):
            assert re.search(pattern, texts[arm], re.IGNORECASE), \
                f"{rule} present for G0 but missing from {arm}"
