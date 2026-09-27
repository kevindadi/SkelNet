"""`.env` must be git-ignored and never tracked."""

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO), *args],
                          capture_output=True, text=True)


def test_env_is_ignored():
    assert (REPO / ".env").exists(), "expected a local .env (copied in P0)"
    out = _git("check-ignore", "-v", ".env")
    assert out.returncode == 0
    assert ".env" in out.stdout


def test_env_is_not_tracked():
    out = _git("ls-files")
    assert out.returncode == 0
    tracked = [line for line in out.stdout.splitlines() if line.endswith("/.env") or line == ".env"]
    assert tracked == []


def test_env_example_has_no_values():
    text = (REPO / ".env.example").read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        assert key
        assert value == "", f"{key} has a value in .env.example"
