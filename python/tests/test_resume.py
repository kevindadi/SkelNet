"""B5: --resume only runs missing cells and rejects mismatched parameters."""

import pytest

from skelnet import cli
from skelnet.oracle import FakeOracle

from _fake_sdk import RUST, ScriptedTransportClient, run_args


def test_resume_runs_only_missing_cells(tmp_path):
    out = tmp_path / "run"
    client = ScriptedTransportClient([RUST, RUST])
    cli.cmd_run(run_args("G0", out, reps=2),
                client_factory=lambda spec, o: client,
                oracle_factory=lambda t, term: FakeOracle(True))
    target = out / "cells" / "lock-order" / "abba_2lock" / "1" / "result.json"
    assert target.exists()
    target.unlink()

    # A fresh cache dir so the resumed rep is not answered from the first run's
    # cache (identical prompts with no per-cell seed).
    client2 = ScriptedTransportClient([RUST])
    rc = cli.cmd_run(run_args("G0", out, reps=2, resume=True,
                              cache_dir=str(tmp_path / "resume-cache")),
                     client_factory=lambda spec, o: client2,
                     oracle_factory=lambda t, term: FakeOracle(True))
    assert rc == 0
    assert target.exists()
    assert len(client2.calls) == 1


def test_resume_rejects_mismatched_params(tmp_path):
    out = tmp_path / "run"
    cli.cmd_run(run_args("G0", out, reps=1),
                client_factory=lambda spec, o: ScriptedTransportClient([RUST]),
                oracle_factory=lambda t, term: FakeOracle(True))
    with pytest.raises(SystemExit):
        cli.cmd_run(run_args("G0", out, reps=1, rounds=5, resume=True),
                    client_factory=lambda spec, o: ScriptedTransportClient([RUST]),
                    oracle_factory=lambda t, term: FakeOracle(True))
