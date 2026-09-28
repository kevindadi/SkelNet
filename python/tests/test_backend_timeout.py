"""E1: a backend timeout is isolated to one cell and the run completes."""

import json
import subprocess
from types import SimpleNamespace

from skelnet import backend, cli
from skelnet.oracle import FakeOracle

from _fake_sdk import RUST, ScriptedTransportClient, run_args


def test_backend_timeout_is_isolated(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_run(cmd, cwd=None, timeout=300):
        calls["n"] += 1
        if calls["n"] == 1:
            raise subprocess.TimeoutExpired(cmd, timeout)
        if "check" in cmd:
            return SimpleNamespace(returncode=0,
                                   stdout=json.dumps({"valid": True, "diagnostics": []}),
                                   stderr="")
        if "verify" in cmd:
            return SimpleNamespace(returncode=0, stdout=json.dumps({
                "outcome": "PASS", "complete": True, "unmapped": 0,
                "properties": [], "counterexamples": [], "diagnostics": []}), stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(backend, "_run", fake_run)

    out = tmp_path / "run"
    args = run_args("SKEL", out, tasks="lock-order/*", rounds=1)
    rc = cli.cmd_run(args, client_factory=lambda spec, o: ScriptedTransportClient([RUST]),
                     oracle_factory=lambda t, term: FakeOracle(True))
    assert rc == 0
    assert (out / "SUMMARY.json").exists()
    manifest = json.loads((out / "MANIFEST.json").read_text())
    assert manifest["status"] == "complete"

    first = json.loads((out / "cells" / "lock-order" / "abba_2lock" / "0"
                        / "result.json").read_text())
    assert first["history"][0]["status"] == "timeout"
    second = json.loads((out / "cells" / "lock-order" / "cross_module_cycle" / "0"
                         / "result.json").read_text())
    assert second["status"] == "ok"
