"""T2: clippy classification, lint argv order, and a gated real lint."""

import json
from pathlib import Path

from skelnet.rusttools.clippy import CONCURRENCY_LINTS, run_clippy
from skelnet.rusttools.runner import ToolRunner

from round03_helpers import ns
from round04_helpers import clippy_tools


def _message(level, code, message, rendered=None):
    return json.dumps({
        "reason": "compiler-message",
        "message": {
            "level": level,
            "message": message,
            "code": {"code": code} if code else None,
            "rendered": rendered or f"{level}[{code}]: {message}\n --> src/main.rs:1:1\n",
        },
    })


_STDOUT = "\n".join([
    _message("warning", "clippy::mutex_atomic", "this Mutex can be replaced"),
    _message("warning", "unused_variables", "unused variable: `x`"),
    _message("warning", "let_underscore_lock", "non-binding let on a lock"),
    _message("error", "E0425", "cannot find value `missing`"),
])


def test_clippy_classifies_recorded_json(tmp_path):
    def run(cmd, cwd, timeout, env):
        return ns(0, _STDOUT, "")
    result = run_clippy(ToolRunner(runner=run, toolchain="nightly-test"),
                        tmp_path, "fn main() {}\n", timeout=5)
    assert [d.code for d in result.clippy] == ["clippy::mutex_atomic"]
    assert [d.code for d in result.rustc_warnings] == [
        "unused_variables", "let_underscore_lock"]
    assert [d.code for d in result.rustc_errors] == ["E0425"]
    assert result.blocking
    assert "src/main.rs" in result.clippy[0].rendered
    assert str(tmp_path) not in result.clippy[0].rendered


def test_clippy_argv_denies_all_then_warns_lints(tmp_path):
    seen = {}

    def run(cmd, cwd, timeout, env):
        seen["argv"] = list(cmd)
        return ns(0, "", "")
    run_clippy(ToolRunner(runner=run, toolchain="nightly-test"),
               tmp_path, "fn main() {}\n", timeout=5)
    argv = seen["argv"]
    assert argv[0] == "cargo"
    assert "--offline" in argv
    dash = argv.index("--")
    flags = argv[dash + 1:]
    assert flags[:2] == ["-A", "clippy::all"]
    warned = flags[flags.index("-W") + 1::2] if False else [
        flags[i + 1] for i, tok in enumerate(flags) if tok == "-W"]
    assert warned == list(CONCURRENCY_LINTS)


def test_clippy_unavailable_when_component_missing(tmp_path):
    def run(cmd, cwd, timeout, env):
        return ns(1, "", "error: no such command: `clippy`")
    result = run_clippy(ToolRunner(runner=run, toolchain="nightly-test"),
                        tmp_path, "fn main() {}\n", timeout=5)
    assert result.unavailable
    assert not result.blocking


@clippy_tools
def test_real_mutex_bool_reports_mutex_atomic(tmp_path):
    if "clippy::mutex_atomic" not in CONCURRENCY_LINTS:
        import pytest
        pytest.skip("clippy::mutex_atomic is not in the active lint set")
    source = (
        "use std::sync::Mutex;\n"
        "fn main() {\n"
        "    let m = Mutex::new(false);\n"
        "    let _g = m.lock().unwrap();\n"
        "}\n"
    )
    result = run_clippy(ToolRunner(), tmp_path, source, timeout=180)
    assert result.unavailable is None
    assert any(d.code == "clippy::mutex_atomic" for d in result.clippy)
