"""T10: baseline CLI wiring — arm choices, preflight, resume, codegen."""

import json
from pathlib import Path

import pytest

from skelnet import cli
from skelnet.schema import validate_cell as cli_validate

from test_round04_baselines import CLEAN, _CmdRunner


class _One:
    def complete(self, system, user):
        from types import SimpleNamespace
        return SimpleNamespace(
            text=CLEAN, usage=None, requested_model="deepseek-v4-flash",
            response_model=None, request_id="r", transport_attempt=1,
            cost=None, finish_reason="stop")


def _args(tmp_path, *extra, name="run"):
    out = tmp_path / name
    return cli.build_parser().parse_args([
        "run", "--tasks", "lock-order/abba_2lock", "--reps", "1",
        "--rounds", "1", "--out", str(out),
        "--budget-file", str(tmp_path / f"budget-{name}.json"),
        *extra,
    ])


def test_parser_accepts_baseline_arms():
    parser = cli.build_parser()
    for arm in ("REFINE", "STATIC", "DYNAMIC", "DYNAMIC_M"):
        args = parser.parse_args(["run", "--arm", arm, "--dry-run"])
        assert args.arm == arm
    assert parser.parse_args(["run"]).first_round == "auto"
    assert parser.parse_args(["run"]).feedback_miri_seeds == 16
    with pytest.raises(SystemExit):
        parser.parse_args(["run", "--arm", "NOPE"])


def test_preflight_names_the_missing_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_clippy_version", lambda: None)
    args = _args(tmp_path, "--arm", "STATIC")
    with pytest.raises(SystemExit, match="clippy"):
        cli.cmd_run(args, client_factory=lambda spec, out: _One(),
                    oracle_runner=_CmdRunner())


def test_allow_missing_records_tools_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_clippy_version", lambda: None)
    args = _args(tmp_path, "--arm", "STATIC", "--allow-missing-tools",
                 name="allow")
    rc = cli.cmd_run(args, client_factory=lambda spec, out: _One(),
                     oracle_runner=_CmdRunner())
    assert rc == 0
    cell = json.loads(
        (tmp_path / "allow" / "cells" / "lock-order" / "abba_2lock" / "0"
         / "result.json").read_text(encoding="utf-8"))
    assert "clippy" in cell["baseline"]["tools_missing"]
    manifest = json.loads((tmp_path / "allow" / "MANIFEST.json").read_text())
    assert "clippy" in manifest["baseline_tools"]["missing"]
    assert manifest["baseline_tools"]["first_round"] == "auto"


def test_refine_codegen_is_rejected(tmp_path):
    args = _args(tmp_path, "--arm", "REFINE", "--rust-mode", "codegen")
    with pytest.raises(SystemExit, match="codegen"):
        cli.cmd_run(args, client_factory=lambda spec, out: _One(),
                    oracle_runner=_CmdRunner())


def test_feedback_miri_seeds_above_the_window_is_rejected(tmp_path):
    args = _args(tmp_path, "--arm", "G0", "--feedback-miri-seeds", "65")
    with pytest.raises(SystemExit, match="feedback-miri-seeds"):
        cli.cmd_run(args, client_factory=lambda spec, out: _One(),
                    oracle_runner=_CmdRunner())


def test_static_replay_needs_no_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    fixture = Path(__file__).parent / "fixtures" / "round04" / "replay_abba"
    out = tmp_path / "replay"
    args = cli.build_parser().parse_args([
        "run", "--arm", "STATIC", "--tasks", "lock-order/abba_2lock",
        "--reps", "1", "--out", str(out), "--hint", "h0",
        "--replay-from", str(fixture), "--allow-missing-tools",
        "--budget-file", str(tmp_path / "budget-replay.json"),
    ])
    assert cli.cmd_run(args) == 0
    cell = json.loads(
        (out / "cells" / "lock-order" / "abba_2lock" / "0" / "result.json")
        .read_text(encoding="utf-8"))
    assert cell["calls"][0]["cache_hit"] is True
    assert "baseline" in cell
    assert cli_validate(cell) == []


def test_resume_rejects_changed_baseline_tools(tmp_path):
    args = _args(tmp_path, "--arm", "G0", name="resume")
    assert cli.cmd_run(args, client_factory=lambda spec, out: _One(),
                       oracle_runner=_CmdRunner()) == 0
    again = cli.build_parser().parse_args([
        "run", "--arm", "G0", "--tasks", "lock-order/abba_2lock",
        "--reps", "1", "--rounds", "1", "--out", str(tmp_path / "resume"),
        "--budget-file", str(tmp_path / "budget-resume.json"),
        "--resume", "--first-round", "require-cache",
    ])
    with pytest.raises(SystemExit, match="baseline_tools"):
        cli.cmd_run(again, client_factory=lambda spec, out: _One(),
                    oracle_runner=_CmdRunner())
