"""A11: run, calibrate, and fp-check share comma-separated --tasks."""

import json
from types import SimpleNamespace

import pytest

from skelnet import cli
from skelnet.backend import repo_root
from skelnet.oracle import FakeOracle


def test_run_comma_union_preserves_directory_order(tmp_path, capsys):
    pattern = "lock-order/abba_2lock,condvar/*"
    rc = cli.main([
        "run", "--arm", "G0", "--tasks", pattern, "--reps", "1", "--dry-run",
        "--out", str(tmp_path / "dry"),
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    root = repo_root()
    one = cli._select_tasks(root, "lock-order/abba_2lock")
    cond = cli._select_tasks(root, "condvar/*")
    tasks, unmatched = cli.select_task_patterns(root, pattern)
    assert unmatched == []
    assert payload["tasks"] == len(one) + len(cond) == len(tasks)
    base = root / "benchmarks" / "tasks"
    ordered = [str(task.relative_to(base)) for task in tasks]
    assert ordered == sorted(ordered)
    assert ordered[0] == str(tasks[0].relative_to(base))

    class Client:
        def complete(self, system, user):
            return SimpleNamespace(
                text="```rust\nfn main() { println!(\"x\"); }\n```",
                usage=None, requested_model="deepseek-v4-flash",
                response_model=None, request_id="r",
                transport_attempt=1, cost=None, finish_reason="stop")

    out = tmp_path / "run"
    rc = cli.cmd_run(cli.build_parser().parse_args([
        "run", "--arm", "G0", "--tasks", pattern, "--reps", "1",
        "--out", str(out), "--budget-file", str(tmp_path / "budget.json"),
    ]), client_factory=lambda spec, _o: Client(),
        oracle_factory=lambda _t, _term: FakeOracle(True))
    assert rc == 0
    manifest = json.loads((out / "MANIFEST.json").read_text())
    assert manifest["tasks"]["pattern"] == pattern
    assert manifest["tasks"]["selected"] == ordered


def test_run_unmatched_pattern_exits_2(tmp_path, capsys):
    out = tmp_path / "nope"
    rc = cli.main([
        "run", "--arm", "G0", "--tasks", "nope/*", "--reps", "1", "--dry-run",
        "--out", str(out),
    ])
    err = capsys.readouterr().err
    assert rc == 2
    assert "unmatched task patterns: nope/*" in err
    assert not out.exists()


def test_calibrate_and_fp_check_reject_unmatched(tmp_path, capsys):
    cal = tmp_path / "cal"
    rc = cli.main([
        "oracle", "calibrate", "--tasks", "a/*,b/*", "--out", str(cal),
    ])
    err = capsys.readouterr().err
    assert rc == 2
    assert "unmatched task patterns:" in err
    assert not cal.exists()
    fp = tmp_path / "fp"
    rc = cli.main(["tools", "fp-check", "--tasks", "nope", "--out", str(fp)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "unmatched task patterns: nope" in err
    assert not fp.exists()


def test_resume_accepts_the_same_comma_pattern(tmp_path):
    pattern = "lock-order/abba_2lock,lock-order/cycle_3lock"

    class Client:
        def complete(self, system, user):
            return SimpleNamespace(
                text="```rust\nfn main() { println!(\"DONE t1=1 t2=1\"); }\n```",
                usage=None, requested_model="deepseek-v4-flash",
                response_model=None, request_id="r",
                transport_attempt=1, cost=None, finish_reason="stop")

    out = tmp_path / "run"
    common = ["run", "--arm", "G0", "--tasks", pattern, "--reps", "1",
              "--out", str(out), "--budget-file", str(tmp_path / "budget.json")]
    rc = cli.cmd_run(cli.build_parser().parse_args(common),
                     client_factory=lambda spec, _o: Client(),
                     oracle_factory=lambda _t, _term: FakeOracle(True))
    assert rc == 0
    rc = cli.cmd_run(cli.build_parser().parse_args(common + ["--resume"]),
                     client_factory=lambda spec, _o: Client(),
                     oracle_factory=lambda _t, _term: FakeOracle(True))
    assert rc == 0
    other = ["run", "--arm", "G0", "--tasks", "lock-order/abba_2lock",
             "--reps", "1", "--out", str(out), "--resume",
             "--budget-file", str(tmp_path / "budget.json")]
    with pytest.raises(SystemExit, match="tasks do not match"):
        cli.cmd_run(cli.build_parser().parse_args(other),
                    client_factory=lambda spec, _o: Client(),
                    oracle_factory=lambda _t, _term: FakeOracle(True))
