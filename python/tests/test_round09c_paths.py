"""R9c: relative CLI paths must not break the oracle or the MANIFEST.

The Stage-0 defect: ``cmd_run`` kept ``args.out`` relative, so the oracle's
``workdir`` was relative and O2 launched ``target/debug/probe`` with a relative
``cwd``; the child resolved the path against the new cwd and never found the
binary. Two guards are tested independently:

* CLI entry resolution (a fake oracle records an absolute ``workdir``);
* the ``ToolRunner`` fallback (``cmd[0]``/``cwd`` normalized to absolute).
"""

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

from skelnet import cli
from skelnet.oracle import FakeOracle, RustOracle
from skelnet.rusttools.runner import ToolRunner

from _fake_sdk import RUST, TransportOutcome
from round03_helpers import rust_tools

FIXTURE = Path(__file__).parent / "fixtures" / "round03"


def _repo() -> Path:
    return Path(__file__).resolve().parents[2]


class _FixedClient:
    """A ``complete``-only client returning one fixed Rust reply."""

    def __init__(self, text: str) -> None:
        self.text = text

    def set_cell(self, *_args) -> None:
        return None

    def complete(self, system: str, user: str):
        return TransportOutcome(self.text, usage={"prompt_tokens": 1,
                                                  "completion_tokens": 1})


class _RecordingOracle(FakeOracle):
    """Records the ``workdir`` the pipeline passes to the oracle."""

    def __init__(self) -> None:
        super().__init__(True)
        self.workdirs: list[Path] = []

    def evaluate(self, *args, **kwargs):
        self.workdirs.append(Path(args[1]))
        return super().evaluate(*args, **kwargs)


def _run_args(out: str, **extra):
    argv = ["run", "--arm", "G0", "--model", "DeepSeek Flash",
            "--tasks", "lock-order/abba_2lock", "--reps", "1", "--rounds", "1",
            "--out", out]
    for key, value in extra.items():
        argv += ["--" + key.replace("_", "-"), str(value)]
    return cli.build_parser().parse_args(argv)


# ── entry resolution: the oracle sees an absolute workdir ────────────────

def test_run_resolves_relative_out_for_oracle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    recording = _RecordingOracle()
    args = _run_args("experiments/rel", budget_file="rel-budget.json")
    rc = cli.cmd_run(args, client_factory=lambda spec, out: _FixedClient(RUST),
                     oracle_factory=lambda task_dir, terminal: recording)
    assert rc == 0
    assert recording.workdirs and all(w.is_absolute() for w in recording.workdirs)
    assert (tmp_path / "experiments/rel/MANIFEST.json").exists()


def test_manifest_keeps_relative_paths_unresolved(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = _run_args("experiments/man", budget_file="rel-budget.json",
                     cache_dir="rel-cache")
    rc = cli.cmd_run(args, client_factory=lambda spec, out: _FixedClient(RUST),
                     oracle_factory=lambda task_dir, terminal: FakeOracle(True))
    assert rc == 0
    manifest = json.loads((tmp_path / "experiments/man/MANIFEST.json").read_text())
    assert manifest["budget_file"] == "rel-budget.json"
    assert manifest["cache_dir"] == "rel-cache"
    assert manifest["replay_from"] is None


# ── ToolRunner fallback: relative program + relative cwd ─────────────────

def test_tool_runner_executes_relative_program_with_relative_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "work").mkdir()
    binary = tmp_path / "bin" / "hello.sh"
    binary.parent.mkdir()
    binary.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    binary.chmod(0o755)

    call = ToolRunner().run(["bin/hello.sh"], "work")
    assert call.error is None
    assert call.returncode == 0
    assert call.stdout.strip() == "hi"


def test_tool_runner_absolutizes_program_and_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    seen: dict = {}

    def runner(cmd, cwd, timeout, env):
        seen["cmd"] = [str(part) for part in cmd]
        seen["cwd"] = Path(cwd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    tools = ToolRunner(runner=runner)
    tools.run(["bin/hello.sh"], "work")
    assert seen["cmd"][0] == str((tmp_path / "bin" / "hello.sh").resolve())
    assert seen["cwd"] == (tmp_path / "work").resolve()

    # A bare command name keeps going through PATH.
    tools.run(["cargo", "build"], "work")
    assert seen["cmd"][0] == "cargo"


# ── end to end with the real oracle (gated on rust tools) ────────────────

@rust_tools
def test_relative_out_real_oracle_layers_pass(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fixed = (_repo() / "benchmarks/tasks/lock-order/abba_2lock/rust/fixed.rs"
             ).read_text(encoding="utf-8")
    client = _FixedClient("```rust\n" + fixed + "\n```")

    def factory(task_dir, terminal):
        return RustOracle(terminal=terminal, task_dir=task_dir,
                          stress_runs=2, monitor_runs=1)

    args = _run_args("experiments/real", call_budget=2)
    rc = cli.cmd_run(args, client_factory=lambda spec, out: client,
                     oracle_factory=factory)
    assert rc == 0
    cell = json.loads((tmp_path / "experiments/real/cells/lock-order/"
                       "abba_2lock/0/result.json").read_text())
    oracle = cell["oracle"]
    assert oracle["layers"]["O2"]["status"] == "pass", oracle["layers"]["O2"]
    assert oracle["o3_tools"]["shuttle"]["status"] != "unsupported"
    assert oracle["layers"]["O3"].get("category") != "shuttle_unsupported"


@rust_tools
def test_relative_paths_calibrate_and_eval(tmp_path, monkeypatch):
    fx = tmp_path / "fx"
    shutil.copytree(FIXTURE, fx)

    run_rel = "relrun"
    cell_dir = tmp_path / run_rel / "cells/lock-order/abba_2lock/0"
    cell_dir.mkdir(parents=True)
    (cell_dir / "candidate.rs").write_text(
        (fx / "abba_2lock/rust/fixed.rs").read_text(encoding="utf-8"),
        encoding="utf-8")
    (cell_dir / "result.json").write_text(json.dumps(
        {"schema_version": "skelnet-cell-v1", "rust_mode": "llm"}), encoding="utf-8")
    (tmp_path / run_rel / "MANIFEST.json").write_text(json.dumps({
        "hint": "h1", "run_id": run_rel, "arm": "G0", "model": "DeepSeek Flash",
        "tasks": {"selected": ["lock-order/abba_2lock"]}, "reps": 1}),
        encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    rc = cli.main(["oracle", "calibrate", "--fixtures", "fx", "--out", "calout",
                   "--report-only"])
    assert rc == 0
    calibration = json.loads((tmp_path / "calout/CALIBRATION.json").read_text())
    fixed = [p for task in calibration["tasks"] for p in task["programs"]
             if p["program"] == "fixed.rs"][0]
    assert fixed["functional_ok"] is True, fixed
    assert all(fixed["layers"][name]["status"] == "pass"
               for name in ("O1", "O2", "O3", "O4")), fixed["layers"]

    assert cli.main(["eval", run_rel]) == 0
    data = json.loads((cell_dir / "result.json").read_text())
    assert data["oracle"]["functional_ok"] is True, data["oracle"]
