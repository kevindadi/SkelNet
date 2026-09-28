"""T1: the shared tool runner archives calls, pins the toolchain and cleans up."""

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

from skelnet.rusttools.runner import ToolRunner, cleanup_target

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
