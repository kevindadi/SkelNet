"""T2: O1 policy scan — one violation sample and one comment/string decoy each."""

from pathlib import Path

from skelnet.rusttools.policy import evaluate_o1, scan_policy

from round03_helpers import ns

VIOLATIONS = {
    "unsafe": "fn main() { unsafe { } }\n",
    "static_mut": "static mut X: i32 = 0;\nfn main() {}\n",
    "thread_sleep": "fn main() { std::thread::sleep(std::time::Duration::from_secs(1)); }\n",
    "yield_now": "fn main() { std::thread::yield_now(); }\n",
    "process_exit": "fn main() { std::process::exit(0); }\n",
    "process_abort": "fn main() { std::process::abort(); }\n",
    "extern_crate": "extern crate rand;\nfn main() {}\n",
    "feature_gate": "#![feature(test)]\nfn main() {}\n",
    "external_crate": "use rand::Rng;\nfn main() {}\n",
}

DECOYS = {
    "unsafe": '// unsafe\nfn main() { let _ = "unsafe"; }\n',
    "static_mut": '// static mut\nfn main() { let _ = "static mut"; }\n',
    "thread_sleep": '// thread::sleep\nfn main() { let _ = "thread::sleep"; }\n',
    "yield_now": 'fn main() { let _ = "yield_now"; }\n',
    "process_exit": '// process::exit\nfn main() { let _ = "process::exit"; }\n',
    "process_abort": 'fn main() { let _ = "process::abort"; }\n',
    "extern_crate": '// extern crate\nfn main() { let _ = "extern crate"; }\n',
    "feature_gate": '// #![feature\nfn main() {}\n',
    "external_crate": '// use rand::Rng;\nfn main() { let _ = "use rand::Rng;"; }\n',
}


def test_each_rule_has_a_violation_sample():
    for rule, src in VIOLATIONS.items():
        rules = {name for name, _line in scan_policy(src)}
        assert any(name == rule or name.startswith(rule + ":") for name in rules), rule


def test_each_rule_ignores_comments_and_strings():
    for rule, src in DECOYS.items():
        assert not scan_policy(src), rule


def test_allowed_crates_and_local_mods():
    src = ("use std::sync::Arc;\nuse concir_sync::Semaphore;\nuse crate::x;\n"
           "mod helper;\nuse helper::y;\nfn main() {}\n")
    assert not scan_policy(src)


def test_evaluate_o1_reports_categories(tmp_path):
    def runner(cmd, cwd, timeout, env):
        if "build" in cmd:
            return ns(0, "", "")
        return ns(0, "", "")
    from skelnet.rusttools.runner import ToolRunner
    tools = ToolRunner(runner=runner, toolchain=None)
    good = evaluate_o1(tools, tmp_path, "fn main() {}\n")
    assert good.status == "pass"
    bad = evaluate_o1(tools, tmp_path, "fn main() { unsafe {} }\n")
    assert bad.status == "fail" and bad.category == "policy_violation"


def test_evaluate_o1_no_build(tmp_path):
    from skelnet.rusttools.runner import ToolRunner
    tools = ToolRunner(runner=lambda *a: ns(1, "", "boom"), toolchain=None)
    result = evaluate_o1(tools, tmp_path, "fn main() {}\n")
    assert result.status == "fail" and result.category == "no_build"
