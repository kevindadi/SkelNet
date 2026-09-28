"""T1: the shared tool runner archives calls, pins the toolchain and cleans up."""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import round03_helpers
from skelnet.rusttools.runner import ToolRunner, cleanup_target, default_runner

from round03_helpers import ns


def _runner(record):
    def run(cmd, cwd, timeout, env):
        record.append((cmd, env))
        return ns(0, "out", "err")
    return run


def test_runner_archives_hashes_and_env_names(tmp_path):
    record: list = []
    tools = ToolRunner(runner=_runner(record), toolchain="nightly-test")
    tools.run(["cargo", "build"], tmp_path, timeout=5.0, offline=True)
    assert len(tools.records) == 1
    entry = tools.records[0]
    assert entry["argv"][:2] == ["cargo", "--offline"]
    assert "RUSTUP_TOOLCHAIN" in entry["env_keys"]
    assert entry["stdout_sha256"] and entry["stderr_sha256"]
    assert entry["returncode"] == 0
    assert "nightly-test" == record[0][1]["RUSTUP_TOOLCHAIN"]
    # Values are never archived, only names.
    assert all(isinstance(k, str) for k in entry["env_keys"])


def test_runner_marks_timeout(tmp_path):
    def run(cmd, cwd, timeout, env):
        raise subprocess.TimeoutExpired(cmd, timeout)
    call = ToolRunner(runner=run).run(["sleep"], tmp_path, timeout=0.01)
    assert call.timed_out and call.returncode is None


def test_cleanup_target_respects_keep(tmp_path, monkeypatch):
    target = tmp_path / "target"
    target.mkdir()
    (target / "f").write_text("x", encoding="utf-8")
    assert cleanup_target(tmp_path) is True
    assert not target.exists()
    target.mkdir()
    monkeypatch.setenv("SKELNET_KEEP_TARGET", "1")
    assert cleanup_target(tmp_path) is False
    assert target.exists()


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def test_default_runner_kills_the_process_group(tmp_path):
    pidfile = tmp_path / "pid"
    cmd = ["sh", "-c", f"sleep 30 >/dev/null 2>&1 & echo $! > {pidfile}; wait"]
    with pytest.raises(subprocess.TimeoutExpired):
        default_runner(cmd, tmp_path, 0.5, dict(os.environ))
    pid = int(pidfile.read_text(encoding="utf-8").strip())
    for _ in range(50):
        if not _alive(pid):
            break
        time.sleep(0.05)
    assert not _alive(pid), "grandchild survived the timeout"


def test_miri_available_uses_cargo_miri(monkeypatch):
    # A standard rustup has no `miri` proxy on PATH.
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert round03_helpers.miri_available(
        runner=lambda cmd, **kw: ns(0, "miri 0.1.0", "")) is True
    assert round03_helpers.miri_available(
        runner=lambda cmd, **kw: ns(1, "", "unknown proxy name: 'miri'")) is False


def test_reason_mentions_cargo_miri(monkeypatch):
    monkeypatch.setattr(round03_helpers, "miri_available", lambda runner=None: False)
    assert "cargo miri" in round03_helpers._reason()
