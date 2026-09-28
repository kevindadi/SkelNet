"""Gates for round-4 baseline tools.

``clippy_tools`` skips when ``cargo clippy --version`` fails on the repository
toolchain. ``lockbud_tools`` skips when neither ``LOCKBUD_BIN`` nor
``tools/lockbud/target/release/lockbud`` exists. Cargo, miri and Shuttle keep
using ``round03_helpers.rust_tools`` / ``cargo_available``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from round03_helpers import _toolchain


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def clippy_available() -> bool:
    env = dict(os.environ)
    channel = _toolchain()
    if channel:
        env["RUSTUP_TOOLCHAIN"] = channel
    try:
        proc = subprocess.run(["cargo", "clippy", "--version"],
                              capture_output=True, text=True, timeout=120, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def lockbud_path() -> Path | None:
    env = os.environ.get("LOCKBUD_BIN")
    if env and Path(env).is_file():
        return Path(env)
    candidate = _repo_root() / "tools" / "lockbud" / "target" / "release" / "lockbud"
    if candidate.is_file():
        return candidate
    return None


def lockbud_available() -> bool:
    return lockbud_path() is not None


def _clippy_reason() -> str:
    return "clippy is not installed for the pinned toolchain (cargo clippy --version failed)"


def _lockbud_reason() -> str:
    return ("lockbud binary not found (set LOCKBUD_BIN or run "
            "bash scripts/setup_lockbud.sh)")


clippy_tools = pytest.mark.skipif(not clippy_available(), reason=_clippy_reason())
lockbud_tools = pytest.mark.skipif(not lockbud_available(), reason=_lockbud_reason())
