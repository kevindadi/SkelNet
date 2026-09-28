"""C2: the terminating line is chosen by --hint and reaches the oracle."""

import json
from types import SimpleNamespace

from skelnet import cli
from skelnet.cli import read_terminal
from skelnet.oracle import FakeOracle

from _fake_sdk import RUST, ScriptedTransportClient, run_args


def _make_task(tmp_path):
    task = tmp_path / "repo" / "benchmarks" / "tasks" / "lock-order" / "abba_2lock"
    task.mkdir(parents=True)
    (task / "requirements.json").write_text(
        json.dumps({"terminal": "DONE old", "terminal_v2": "DONE new"}),
        encoding="utf-8")
    (task / "REQUIREMENTS.md").write_text("R1. do it\n", encoding="utf-8")
    (task / "REQUIREMENTS.h1.md").write_text("R1. do it\n", encoding="utf-8")
    (task / "contract.json").write_text("{}", encoding="utf-8")
    return task


def test_read_terminal_by_hint(tmp_path):
    task = _make_task(tmp_path)
    assert read_terminal(task, "h0") == "DONE old"
    assert read_terminal(task, "h1") == "DONE new"


def test_read_terminal_falls_back(tmp_path):
    task = tmp_path / "t"
    task.mkdir()
    (task / "requirements.json").write_text(json.dumps({"terminal": "ONLY"}),
                                            encoding="utf-8")
    assert read_terminal(task, "h0") == "ONLY"
    assert read_terminal(task, "h1") == "ONLY"


def test_hint_reaches_oracle_factory(tmp_path, monkeypatch):
    task = _make_task(tmp_path)
    fake_repo = task.parents[3]  # .../repo
    monkeypatch.setattr(cli, "repo_root", lambda: fake_repo)
    monkeypatch.setattr(cli, "Backend",
                        lambda **kw: SimpleNamespace(skelnet=task / "x",
                                                     concir=task / "y"))
    seen: dict = {}

    def factory(task_dir, terminal):
        seen["terminal"] = terminal
        return FakeOracle(True)

    for hint, want in (("h0", "DONE old"), ("h1", "DONE new")):
        out = tmp_path / f"run_{hint}"
        args = run_args("G0", out, hint=hint)
        cli.cmd_run(args, client_factory=lambda spec, o: ScriptedTransportClient([RUST]),
                    oracle_factory=factory)
        assert seen["terminal"] == want
