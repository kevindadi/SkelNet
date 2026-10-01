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

# rule -> (regex, prompts that must state it). "all" = every generation prompt.
RULES = {
    "no_other_crates": (r"(no\s+other\s+crates|No external crates|only the standard "
                        r"library)", "all"),
    "no_unsafe": (r"no\s+`?unsafe", "all"),
    "no_feature": (r"#!\[feature\]", "all"),
    "no_sleep_yield": (r"(sleep.*yield_now|yield_now.*sleep|sleep.{0,40}yield_now)",
                       "all"),
    "no_static_mut": (r"static mut", (SKEL, CIR)),
    "no_extern_crate": (r"extern crate", (SKEL, CIR)),
    "no_process_exit_abort": (r"process::exit", (SKEL, CIR)),
    "no_thread_scope": (r"thread::scope", (SKEL, CIR)),
    "busy_wait": (r"busy[- ]wait", (SKEL, CIR)),
}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_routes_point_at_new_assets():
    assert prompts.route("SKEL", prompts.STAGE_RUST) == (
        "rust_from_skel_v3.md", "rust_runtime_api_v1.md")
    assert prompts.route("CIR", prompts.STAGE_RUST) == (
        "rust_from_cir_v4.md", "rust_runtime_api_v1.md")


def test_old_prompt_files_are_kept():
    assert (PROMPT_DIR / "rust_from_skel_v2.md").is_file()
    assert (PROMPT_DIR / "rust_from_cir_v3.md").is_file()


def test_rule_table_across_generation_prompts():
    texts = {G0: _text(G0), SKEL: _text(SKEL), CIR: _text(CIR)}
    for rule, (pattern, required) in RULES.items():
        targets = list(texts) if required == "all" else list(required)
        for target in targets:
            assert re.search(pattern, texts[target], re.IGNORECASE), \
                f"{rule} missing from {target.name}"


def test_skel_cir_are_not_less_strict_than_g0():
    # Every rule the G0 prompt states must also appear in both skeleton prompts.
    g0 = _text(G0)
    for rule, (pattern, required) in RULES.items():
        if required != "all":
            continue
        if re.search(pattern, g0, re.IGNORECASE):
            for target in (SKEL, CIR):
                assert re.search(pattern, _text(target), re.IGNORECASE), \
                    f"{rule} present in G0 but missing from {target.name}"
