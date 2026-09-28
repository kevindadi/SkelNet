"""T7: ``python -m skelnet tools fp-check`` through the real CLI."""

import json
from pathlib import Path

from skelnet import cli
from skelnet.rusttools.runner import ToolRunner

from round03_helpers import ns


def _message(code, message):
    return json.dumps({
        "reason": "compiler-message",
        "message": {"level": "warning", "message": message,
                    "code": {"code": code},
                    "rendered": f"warning[{code}]: {message}\n"},
    })


def test_fp_check_command_uses_fake_runner(tmp_path, monkeypatch):
    """The outermost runner is selected by the program source, not a constant."""
    def run(cmd, cwd, timeout, env):
        cmd = [str(part) for part in cmd]
        source = ""
        for base in (Path(cwd), *Path(cwd).parents):
            candidate = base / "src" / "main.rs"
            if candidate.is_file():
                source = candidate.read_text(encoding="utf-8")
                break
        flagged = "mtx_c" in source
        if "clippy" in cmd:
            if flagged:
                return ns(0, _message("clippy::mutex_atomic", "mutex of bool"), "")
            return ns(0, "", "")
        if env.get("RUSTC_WRAPPER"):
            if flagged:
                return ns(0, '{"bug_kind":"DoubleLock"}',
                          "bug_level_stat: conflictlock: 0")
            # Summary line always mentions conflictlock; that is not a finding.
            return ns(0, "bug_level_stat: deadlock: 0, conflictlock: 0\n", "")
        return ns(0, "", "")

    monkeypatch.setattr("skelnet.rusttools.runner.default_runner", run)
    binary = tmp_path / "lockbud"
    binary.write_text("x", encoding="utf-8")
    monkeypatch.setenv("LOCKBUD_BIN", str(binary))
    out = tmp_path / "fp"
    rc = cli.main(["tools", "fp-check", "--tasks", "lock-order/*",
                   "--out", str(out)])
    assert rc == 0
    document = json.loads((out / "FP_CHECK.json").read_text(encoding="utf-8"))
    by_task = {row["task"]: row for row in document["tasks"]}
    abba = by_task["lock-order/abba_2lock"]["programs"]
    cycle = by_task["lock-order/cycle_3lock"]["programs"]
    assert abba[0]["role"] == "fixed"
    assert abba[0]["clippy"]["findings"] == []
    assert abba[0]["lockbud"]["records"] == []
    assert any(f["code"] == "clippy::mutex_atomic" for f in cycle[0]["clippy"]["findings"])
    assert cycle[0]["lockbud"]["records"][0]["bug_kind"] == "DoubleLock"
    assert document["summary"]["clippy"]["fixed_fp_rate"] is not None
    assert "false-positive" in (out / "FP_CHECK.md").read_text(encoding="utf-8")
    assert ToolRunner().runner is run
