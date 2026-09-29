"""A7: hint default, requirements preflight, and the stage gate."""

import json
from types import SimpleNamespace

import pytest

from skelnet import cli, params
from skelnet.oracle import FakeOracle


def _task(root, rel, *, h0=True, h1=True):
    task = root / "benchmarks" / "tasks" / rel
    task.mkdir(parents=True)
    (task / "contract.json").write_text("{}\n", encoding="utf-8")
    (task / "requirements.json").write_text(
        json.dumps({"terminal": "DONE t=1"}) + "\n", encoding="utf-8")
    if h0:
        (task / "REQUIREMENTS.md").write_text("R1. Work.\n", encoding="utf-8")
    if h1:
        (task / "REQUIREMENTS.h1.md").write_text("R1. Work.\n", encoding="utf-8")
    return task


def _client():
    box = {"n": 0}

    class Client:
        def complete(self, system, user):
            box["n"] += 1
            return SimpleNamespace(
                text="```rust\nfn main() { println!(\"DONE t=1\"); }\n```",
                usage=None, requested_model="deepseek-v4-flash",
                response_model=None, request_id="r",
                transport_attempt=1, cost=None, finish_reason="stop")

    return Client, box


def test_default_hint_follows_params_constant(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    _task(root, "fam/one")
    monkeypatch.setattr(cli, "repo_root", lambda: root)
    monkeypatch.setattr(params, "DEFAULT_HINT", "h1")
    seen = []
    monkeypatch.setattr(cli, "render_requirements", lambda task, hint="h0": seen.append(("render", hint)) or "R1. Work.\n")
    monkeypatch.setattr(cli, "read_terminal", lambda task, hint="h1": seen.append(("read", hint)) or "DONE t=1")
    Client, box = _client()
    out = tmp_path / "run"
    args = cli.build_parser().parse_args([
        "run", "--arm", "G0", "--tasks", "fam/one", "--reps", "1",
        "--out", str(out), "--budget-file", str(tmp_path / "budget.json"),
    ])
    assert args.hint is None
    rc = cli.cmd_run(args, client_factory=lambda spec, _o: Client(),
                     oracle_factory=lambda _t, _term: FakeOracle(True))
    assert rc == 0
    manifest = json.loads((out / "MANIFEST.json").read_text())
    assert manifest["hint_source"] == "default"
    assert manifest["hint"] == "h1"
    assert manifest["run_params"]["hint"] == "h1"
    assert ("render", "h1") in seen
    assert ("read", "h1") in seen
    assert box["n"] == 1


def test_missing_hint_file_exits_before_any_call(tmp_path, monkeypatch, capsys):
    root = tmp_path / "repo"
    _task(root, "fam/one", h1=False)
    monkeypatch.setattr(cli, "repo_root", lambda: root)
    Client, box = _client()
    out = tmp_path / "run"
    args = cli.build_parser().parse_args([
        "run", "--arm", "G0", "--tasks", "fam/one", "--reps", "1",
        "--hint", "h1", "--out", str(out),
        "--budget-file", str(tmp_path / "budget.json"),
    ])
    with pytest.raises(SystemExit, match="fam/one"):
        cli.cmd_run(args, client_factory=lambda spec, _o: Client(),
                    oracle_factory=lambda _t, _term: FakeOracle(True))
    assert box["n"] == 0
    assert not out.exists()


def test_dry_run_lists_missing_requirements(tmp_path, monkeypatch, capsys):
    root = tmp_path / "repo"
    _task(root, "fam/one", h1=False)
    _task(root, "boundary/edge", h0=False, h1=False)
    monkeypatch.setattr(cli, "repo_root", lambda: root)
    rc = cli.main([
        "run", "--arm", "G0", "--tasks", "all", "--reps", "1", "--hint", "h1",
        "--dry-run", "--out", str(tmp_path / "unused"),
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["hint_source"] == "explicit"
    assert payload["requirements_missing"] == ["fam/one"]
    assert "requirements_missing" in payload


def test_stage_requires_h1_unless_overridden(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    _task(root, "fam/one")
    monkeypatch.setattr(cli, "repo_root", lambda: root)
    Client, box = _client()
    base = ["run", "--arm", "G0", "--tasks", "fam/one", "--reps", "1",
            "--stage", "1", "--hint", "h0", "--out", str(tmp_path / "run"),
            "--budget-file", str(tmp_path / "budget.json")]
    with pytest.raises(SystemExit, match="D10"):
        cli.cmd_run(cli.build_parser().parse_args(base),
                    client_factory=lambda spec, _o: Client(),
                    oracle_factory=lambda _t, _term: FakeOracle(True))
    assert box["n"] == 0
    out = tmp_path / "allowed"
    args = cli.build_parser().parse_args([
        "run", "--arm", "G0", "--tasks", "fam/one", "--reps", "1",
        "--stage", "1", "--hint", "h0", "--allow-nonprotocol-hint",
        "--out", str(out), "--budget-file", str(tmp_path / "budget2.json"),
    ])
    rc = cli.cmd_run(args, client_factory=lambda spec, _o: Client(),
                     oracle_factory=lambda _t, _term: FakeOracle(True))
    assert rc == 0
    manifest = json.loads((out / "MANIFEST.json").read_text())
    assert manifest["hint_override"] is True
    assert manifest["hint"] == "h0"


def test_eval_legacy_manifest_stays_h0(tmp_path, monkeypatch):
    monkeypatch.setattr(params, "DEFAULT_HINT", "h1")
    run = tmp_path / "old"
    cell = run / "cells" / "lock-order" / "abba_2lock" / "0"
    cell.mkdir(parents=True)
    (cell / "candidate.rs").write_text("fn main() {}\n", encoding="utf-8")
    (cell / "result.json").write_text(json.dumps({
        "schema_version": "skelnet-cell-v1", "arm": "G0", "model": "m",
        "model_id": "m", "task": "lock-order/abba_2lock", "tier": None,
        "hint": "h0", "rep": 0, "seed": 1, "status": "ok", "accepted": True,
        "parse_ok": True, "check_ok": True, "rounds_used": 1, "history": [],
        "ledger": {}, "evidence_sufficient": False, "rust_mode": "llm",
        "calls": [], "budget_used": {"calls": 0, "tokens": 0},
        "oracle": {"built": False, "ran": False, "run_ok": False,
                   "functional_ok": None, "terminal_check": "not_run"},
    }), encoding="utf-8")
    (run / "MANIFEST.json").write_text(json.dumps({
        "run_id": "old", "arm": "G0", "model": "m",
        "tasks": {"selected": ["lock-order/abba_2lock"]}, "reps": 1,
    }), encoding="utf-8")
    seen = []

    def read(task_dir, hint="h1"):
        seen.append(hint)
        return "DONE t1=1 t2=1"

    monkeypatch.setattr(cli, "read_terminal", read)
    rc = cli.cmd_eval(cli.build_parser().parse_args(["eval", str(run)]),
                      runner=lambda cmd, cwd, timeout, env: SimpleNamespace(
                          returncode=0, stdout="DONE t1=1 t2=1\n", stderr=""))
    assert rc == 0
    assert seen == ["h0"]
