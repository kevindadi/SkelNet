"""A4: sequence replay follows call position when tool feedback changes."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from skelnet import cli
from skelnet.oracle import FakeOracle

TERMINAL = "DONE t1=1 t2=1"
RUST = f"```rust\nfn main() {{\n    println!(\"{TERMINAL}\");\n}}\n```"


class _Client:
    def __init__(self, replies):
        self.replies = list(replies)
        self.n = 0

    def complete(self, system, user):
        self.n += 1
        text = self.replies[self.n - 1] if self.n <= len(self.replies) else RUST
        return SimpleNamespace(
            text=text, usage=None, requested_model="deepseek-v4-flash",
            response_model=None, request_id="r",
            transport_attempt=1, cost=None, finish_reason="stop")


class _StressRunner:
    """First dyn_probe run can hang; miri always fails so a second call is issued."""

    def __init__(self, *, hang_first: bool):
        self.hang_first = hang_first
        self.dyn_runs = 0

    def __call__(self, cmd, cwd, timeout, env):
        cmd = [str(part) for part in cmd]
        name = Path(cmd[0]).name
        if name == "dyn_probe":
            self.dyn_runs += 1
            if self.hang_first and self.dyn_runs == 1:
                raise subprocess.TimeoutExpired(cmd, timeout)
            return SimpleNamespace(returncode=0, stdout=TERMINAL + "\n", stderr="")
        if "miri" in cmd:
            return SimpleNamespace(returncode=1, stdout="", stderr="error: undefined behavior: borrow")
        if "build" in cmd:
            self._make_binary(Path(cwd))
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if env.get("CIR_TRACE_OUT"):
            Path(env["CIR_TRACE_OUT"]).write_text("", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout=TERMINAL + "\n", stderr="")

    def _make_binary(self, cwd: Path):
        name = "probe"
        toml = cwd / "Cargo.toml"
        if toml.is_file():
            for line in toml.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("name"):
                    name = line.split("=", 1)[1].strip().strip('"')
                    break
        binary = cwd / "target" / "debug" / name
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text("", encoding="utf-8")


def _factory(replies, holder, key):
    def factory(spec, out):
        holder[key] = _Client(replies)
        return holder[key]
    return factory


def _args(tmp_path, out, arm, extra):
    return cli.build_parser().parse_args([
        "run", "--arm", arm, "--tasks", "lock-order/abba_2lock",
        "--reps", "1", "--rounds", "1", "--call-budget", "2",
        "--out", str(out), "--allow-missing-tools",
        "--budget-file", str(tmp_path / f"budget-{out.name}.json"),
        *extra,
    ])


def test_sequence_replay_survives_a_changed_stress_result(tmp_path):
    holder = {}
    recorded = tmp_path / "recorded"
    rc = cli.cmd_run(
        _args(tmp_path, recorded, "DYNAMIC", []),
        client_factory=_factory([RUST, RUST], holder, "record"),
        oracle_runner=_StressRunner(hang_first=True),
        oracle_factory=lambda _t, _term: FakeOracle(True))
    assert rc == 0
    assert holder["record"].n == 2
    cell = json.loads((recorded / "cells" / "lock-order" / "abba_2lock" / "0" / "result.json").read_text())
    assert len(cell["calls"]) == 2

    def replay(mode, name):
        box = {}
        out = tmp_path / name
        code = cli.cmd_run(
            _args(tmp_path, out, "DYNAMIC", ["--replay-from", str(recorded), "--replay-mode", mode]),
            client_factory=_factory([RUST, RUST], box, "replay"),
            oracle_runner=_StressRunner(hang_first=False),
            oracle_factory=lambda _t, _term: FakeOracle(True))
        path = out / "cells" / "lock-order" / "abba_2lock" / "0" / "result.json"
        body = json.loads(path.read_text()) if path.is_file() else {}
        return code, body, box["replay"]

    key_rc, key_cell, key_client = replay("key", "key")
    assert key_rc == 0
    assert key_client.n == 0
    assert any("replay_miss" in (call.get("error") or "") for call in key_cell["calls"])

    seq_rc, seq_cell, seq_client = replay("sequence", "sequence")
    assert seq_rc == 0
    assert seq_client.n == 0
    assert len(seq_cell["calls"]) == 2
    assert seq_cell["calls"][1]["replay_mismatch"] is True
    assert "replay_mismatch" not in seq_cell["calls"][0]


def test_arms_keep_separate_sequence_indexes(tmp_path):
    cache = tmp_path / "shared"
    holder = {}
    for arm, name in (("G0", "g0"), ("STATIC", "static")):
        stub = tmp_path / f"lockbud-{name}"
        stub.write_bytes(b"")
        # STATIC only. G0 ignores LOCKBUD_BIN.
        if arm == "STATIC":
            import os
            os.environ["LOCKBUD_BIN"] = str(stub)
        runner = _StressRunner(hang_first=False)
        rc = cli.cmd_run(
            _args(tmp_path, tmp_path / name, arm, ["--cache-dir", str(cache)]),
            client_factory=_factory([RUST], holder, arm),
            oracle_runner=runner,
            oracle_factory=lambda _t, _term: FakeOracle(True))
        assert rc == 0, arm
    indexes = list((cache / "sequence").glob("*.json"))
    arms = {json.loads(path.read_text())["arm"] for path in indexes}
    keys = {json.loads(path.read_text())["key"] for path in indexes
            if json.loads(path.read_text())["call_index"] == 1}
    assert arms >= {"G0", "STATIC"}
    assert len(keys) == 1
    os_mod = __import__("os")
    os_mod.environ.pop("LOCKBUD_BIN", None)


def test_sequence_without_replay_from_is_rejected(tmp_path):
    import pytest
    args = _args(tmp_path, tmp_path / "out", "G0", ["--replay-mode", "sequence"])
    with pytest.raises(SystemExit, match="requires --replay-from"):
        cli.cmd_run(args, client_factory=_factory([RUST], {}, "x"),
                    oracle_factory=lambda _t, _term: FakeOracle(True))


def test_old_cache_without_sequence_index_errors(tmp_path):
    import pytest
    recorded = tmp_path / "old"
    rc = cli.cmd_run(
        _args(tmp_path, recorded, "G0", []),
        client_factory=_factory([RUST], {}, "c"),
        oracle_runner=_StressRunner(hang_first=False),
        oracle_factory=lambda _t, _term: FakeOracle(True))
    assert rc == 0
    sequence = recorded / "cache" / "sequence"
    assert sequence.is_dir()
    for child in sequence.iterdir():
        child.unlink()
    sequence.rmdir()
    with pytest.raises(SystemExit, match="replay cache has no sequence index"):
        cli.cmd_run(
            _args(tmp_path, tmp_path / "replay", "G0",
                  ["--replay-from", str(recorded), "--replay-mode", "sequence"]),
            client_factory=_factory([RUST], {}, "r"),
            oracle_factory=lambda _t, _term: FakeOracle(True))
