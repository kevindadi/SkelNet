"""T6: baseline prompt routes, shared format section, user-prompt shape."""

from skelnet import prompts


def _format_section(name: str) -> str:
    text = prompts.read_asset(name)
    start = text.index("<!-- format-rules -->")
    end = text.index("<!-- /format-rules -->") + len("<!-- /format-rules -->")
    return text[start:end]


def test_generate_routes_match_g0_bytes():
    g0 = prompts.system_prompt_for("G0", prompts.STAGE_GENERATE)
    assert g0.encode().hex().startswith("")  # hashed below
    digest = __import__("hashlib").sha256(g0.encode()).hexdigest()
    assert digest.startswith("d2a9b5bf16fd7a78")  # v2 runtime appendix (round 9d fix)
    for arm in prompts.BASELINE_ARMS:
        assert prompts.system_prompt_for(arm, "generate") == g0
        assert prompts.route(arm, "generate") == prompts.route("G0", "generate")


def test_rust_fix_routes_share_one_system_prompt():
    ref = prompts.system_prompt_for("REFINE", "rust_fix")
    for arm in prompts.BASELINE_ARMS:
        assert prompts.system_prompt_for(arm, "rust_fix") == ref
    assert prompts.RUST_COMPILE_FIX_ASSET in prompts.route("STATIC", "rust_fix")


def test_feedback_prompts_differ_but_format_section_matches():
    assets = [
        prompts.RUST_SELF_REFINE_ASSET,
        prompts.RUST_STATIC_FEEDBACK_ASSET,
        prompts.RUST_DYNAMIC_FEEDBACK_ASSET,
        prompts.RUST_DYNAMIC_MONITOR_FEEDBACK_ASSET,
    ]
    bodies = [prompts.read_asset(name) for name in assets]
    assert len(set(bodies)) == 4
    sections = [_format_section(name) for name in assets]
    assert len(set(sections)) == 1
    section = sections[0]
    assert "```rust" in section
    assert "concir_sync" in section
    assert "sleep" in section
    assert "unsafe" in section


def test_review_and_tool_user_prompts():
    review = prompts.baseline_review_user_prompt("need a lock", "fn main() {}")
    assert "<domain_requirements>" in review
    assert "<current_program>" in review
    assert "NO_ISSUES" in review
    assert "```rust" in review
    tool = prompts.baseline_tool_feedback_user_prompt(
        "need a lock", "fn main() {}", "deadlock", source="static")
    assert '<tool_feedback source="static">' in tool
    assert "deadlock" in tool
    assert tool.strip().endswith("Output one ```rust code block.")
    dynamic = prompts.baseline_tool_feedback_user_prompt(
        "need a lock", "fn main() {}", "hang", source="dynamic")
    monitor = prompts.baseline_tool_feedback_user_prompt(
        "need a lock", "fn main() {}", "unmapped", source="dynamic_monitor")
    assert 'source="dynamic"' in dynamic
    assert 'source="dynamic_monitor"' in monitor
