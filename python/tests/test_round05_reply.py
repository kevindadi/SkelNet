"""T2: Rust reply classification, the rust_fix stage and its routing."""

import hashlib

from skelnet import prompts
from skelnet.cli import _ChatProvider
from skelnet.params import RunParams
from skelnet.pipeline import RustReply, classify_rust_reply
from skelnet.providers import CandidateRequest


class _Outcome:
    def __init__(self, text: str) -> None:
        self.text = text
        self.usage = None
        self.requested_model = "deepseek-flash"
        self.response_model = None
        self.request_id = None
        self.transport_attempt = 1
        self.cost = None
        self.cache_hit = False
        self.finish_reason = "stop"
        self.finish_reasons = ["stop"]
        self.usage_attempts = []
        self.temperature_sent = None
        self.wall_ms = 0


class _Client:
    def __init__(self, text: str = "```rust\nfn main() {}\n```") -> None:
        self.text = text
        self.calls: list[tuple[str, str]] = []

    def set_stage(self, _stage):  # pragma: no cover - trivial
        pass

    def set_attempt(self, _attempt):  # pragma: no cover - trivial
        pass

    def set_prompt_meta(self, _assets, _sha):  # pragma: no cover - trivial
        pass

    def complete(self, system: str, user: str):
        self.calls.append((system, user))
        return _Outcome(self.text)


# ── classification ───────────────────────────────────────────────────
def test_classify_no_issues_variants():
    for text in ("NO_ISSUES", "no issues", "No-Issues!", "  NOISSUES  "):
        assert classify_rust_reply(text, allow_no_issues=True).kind == "no_issues"


def test_no_issues_is_other_when_not_allowed():
    assert classify_rust_reply("NO_ISSUES").kind == "other"


def test_classify_bare_program_without_fence():
    reply = classify_rust_reply("fn main() { println!(\"x\"); }")
    assert reply.kind == "program" and "fn main" in reply.source


def test_classify_fenced_without_main_is_other():
    assert classify_rust_reply("```rust\nlet x = 1;\n```").kind == "other"


def test_classify_empty_is_other():
    assert classify_rust_reply("").kind == "other"


# ── user prompt ──────────────────────────────────────────────────────
def test_compile_fix_user_prompt_structure():
    prompt = prompts.rust_compile_fix_user_prompt(
        "two workers", "fn main() { x }", "error[E0425]: cannot find value `x`",
        design="skeleton abba;", design_kind="skel")
    assert "<domain_requirements>" in prompt
    assert "<previous_program>" in prompt
    assert "<rustc_diagnostics>" in prompt
    assert "<skeleton>" in prompt and "</skeleton>" in prompt
    assert "```rust" in prompt


def test_compile_fix_user_prompt_concir_and_no_design():
    prompt = prompts.rust_compile_fix_user_prompt(
        "reqs", "fn main() {}", "error", design="{...}", design_kind="cir")
    assert "<concir>" in prompt and "<skeleton>" not in prompt
    plain = prompts.rust_compile_fix_user_prompt("reqs", "fn main() {}", "error")
    assert "<skeleton>" not in plain and "<concir>" not in plain


# ── property id presentation ─────────────────────────────────────────
def test_present_property_id_keep_and_opaque():
    index: dict[str, str] = {}
    assert prompts.present_property_id("preserved: x", "keep", index) == "preserved: x"
    assert prompts.present_property_id("p1", "opaque", index) == "P1"
    assert prompts.present_property_id("p2", "opaque", index) == "P2"
    assert prompts.present_property_id("p1", "opaque", index) == "P1"


# ── routing through the provider ─────────────────────────────────────
def test_rust_fix_routing_through_chat_provider():
    client = _Client()
    provider = _ChatProvider(client, arm="SKEL", params=RunParams())
    request = CandidateRequest(
        requirements="two workers", contract=None, feedback="error[E0425]: ...",
        attempt=3, previous_candidate="skeleton abba;", current_program="fn main() { x }",
        stage="rust_fix")
    response = provider.propose(request)
    assert response.error is None
    system, user = client.calls[0]
    expected = hashlib.sha256(prompts.PROMPT_SEPARATOR.join(
        prompts.read_asset(a) for a in prompts.route("SKEL", "rust_fix")
    ).encode("utf-8")).hexdigest()
    assert provider.calls[0]["system_sha256"] == expected
    assert provider.calls[0]["stage"] == "rust_fix"
    assert "<rustc_diagnostics>" in user and "<skeleton>" in user


def test_rust_fix_route_uses_compile_fix_asset():
    assert prompts.route("CIR", "rust_fix") == (
        prompts.RUST_COMPILE_FIX_ASSET, prompts.RUST_RUNTIME_API_ASSET)


# ── T8: neutral rust prompts ─────────────────────────────────────────
def test_rust_routes_are_neutral():
    for arm in ("SKEL", "CIR"):
        text = prompts.system_prompt_for(arm, prompts.STAGE_RUST).lower()
        assert "verified" not in text, arm


def test_rust_user_prompts_are_neutral():
    assert "verified" not in prompts.rust_from_skel_user_prompt("r", "s").lower()
    assert "verified" not in prompts.rust_from_cir_user_prompt("r", "c").lower()


def test_prompt_asset_record_has_new_assets():
    record = prompts.prompt_asset_record()
    assert prompts.RUST_FROM_SKEL_V2_ASSET in record
    assert prompts.RUST_FROM_CIR_V3_ASSET in record
