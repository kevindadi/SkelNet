"""F5: deterministic codegen mode scores build+exit and persists cir_trace.rs."""

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

from skelnet import cli
from skelnet.backend import repo_root
from skelnet.oracle import RustOracle

TASK = "lock-order/abba_2lock"

BUGGY = """```skel
skeleton abba_bug;
mutex a;
mutex b;
fn main() { scope { spawn t1(); spawn t2(); } }
fn t1() { lock a { lock b { } } }
fn t2() { lock b { lock a { } } }
```"""

FIXED = """```skel
skeleton abba_ok;
mutex a;
mutex b;
fn main() { scope { spawn t1(); spawn t2(); } }
fn t1() { lock a { lock b { } } }
fn t2() { lock a { lock b { } } }
```"""


class _Outcome:
    def __init__(self, text: str) -> None:
        self.text = text
        self.usage = None
        self.requested_model = "deepseek-flash"
        self.response_model = None
        self.request_id = None
        self.transport_attempt = 1
        self.cost = None


class _Client:
    def __init__(self, texts: list[str]) -> None:
        self.texts = list(texts)
        self._cursor = 0

    def complete(self, system: str, user: str):
        text = self.texts[self._cursor] if self._cursor < len(self.texts) else ""
        self._cursor += 1
        return _Outcome(text)


def _runner(recorder: list[bool] | None = None, run_rc: int = 0):
    def run(cmd, cwd, timeout):
        cwd = Path(cwd)
        if recorder is not None:
            recorder.append((cwd / "src" / "cir_trace.rs").exists())
        if "build" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=run_rc, stdout="", stderr="")
    return run


def _run_codegen(arm: str, texts: list[str], tmp_path: Path, name: str) -> Path:
    out = tmp_path / name
    args = cli.build_parser().parse_args([
        "run", "--arm", arm, "--tasks", TASK, "--reps", "1", "--rounds", "2",
        "--rust-mode", "codegen", "--out", str(out)])
    rc = cli.cmd_run(args, client_factory=lambda spec, o: _Client(texts),
                     oracle=RustOracle(runner=_runner()))
    assert rc == 0
    return out


def test_codegen_skel_cell_persists_cir_trace(tmp_path):
    out = _run_codegen("SKEL", [BUGGY, FIXED], tmp_path, "skel")
    cell = out / "cells" / TASK / "0"
    assert (cell / "cir_trace.rs").exists()
    result = json.loads((cell / "result.json").read_text())
    assert result["oracle"]["terminal_check"] == "not_applicable"
    assert result["oracle"]["functional_ok"] is None
    assert result["oracle"]["run_ok"] is True


def test_codegen_cir_cell_persists_cir_trace(tmp_path):
    gold = (repo_root() / "benchmarks" / "tasks" / TASK / "gold.cir.json").read_text()
    out = _run_codegen("CIR", [gold], tmp_path, "cir")
    cell = out / "cells" / TASK / "0"
    assert (cell / "cir_trace.rs").exists()
    result = json.loads((cell / "result.json").read_text())
    assert result["oracle"]["terminal_check"] == "not_applicable"
    assert result["oracle"]["functional_ok"] is None


def test_eval_rebuilds_codegen_project_with_cir_trace(tmp_path):
    out = _run_codegen("SKEL", [BUGGY, FIXED], tmp_path, "evalskel")
    cell = out / "cells" / TASK / "0"
    shutil.rmtree(cell / "src")  # the oracle's build directory is disposable
    recorder: list[bool] = []
    args = cli.build_parser().parse_args(["eval", str(out)])
    rc = cli.cmd_eval(args, runner=_runner(recorder=recorder))
    assert rc == 0
    assert recorder, "runner was not called"
    assert any(recorder), "eval did not hand src/cir_trace.rs to the runner"
