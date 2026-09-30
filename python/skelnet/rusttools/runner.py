"""Shared subprocess runner for every oracle tool.

All external commands (cargo, miri, the Shuttle project, ``concir-instrument``
and ``concir-backend``) go through one injectable ``runner(cmd, cwd, timeout,
env)``. The :class:`ToolRunner` adds the oracle's fixed environment (offline +
pinned ``RUSTUP_TOOLCHAIN``), process-group timeouts, and a hash-only archive of
every call. Tests replace only the innermost ``runner``; the layer logic above
it is never stubbed.
"""

from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from .base import ToolCall


def _sha(text: str | None) -> str | None:
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _absolutize_program(full_cmd: list[str]) -> list[str]:
    """Resolve a relative program path against the *process* working directory.

    A bare command name (``cargo``) has no path separator and is left for
    ``execvp`` to find on ``PATH``. A command that names a path (contains a
    separator) is resolved here, before the child changes directory, so a
    relative binary path is never re-interpreted relative to ``cwd`` (round 9c:
    a relative ``--out`` doubled the path and broke O2).
    """
    if not full_cmd:
        return full_cmd
    program = full_cmd[0]
    if os.path.isabs(program):
        return full_cmd
    if os.sep in program or (os.altsep and os.altsep in program):
        resolved = str((Path.cwd() / program).resolve())
        return [resolved, *full_cmd[1:]]
    return full_cmd


def default_runner(cmd: list[str], cwd: Path, timeout: float,
                   env: dict[str, str]) -> Any:
    """Run ``cmd`` in its own process group; kill the group on timeout.

    ``start_new_session=True`` plus ``os.killpg`` guarantees that a child
    spawned by ``cargo run`` does not outlive a timeout.
    """
    proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=env,
                            start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        proc.communicate()
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


class ToolRunner:
    def __init__(self, *, runner: Callable[..., Any] | None = None,
                 toolchain: str | None = None,
                 base_env: dict[str, str] | None = None) -> None:
        self.runner = runner or default_runner
        if toolchain is None:
            from ..oracle import repo_toolchain_channel
            toolchain = repo_toolchain_channel()
        self.toolchain = toolchain
        self.base_env = dict(base_env) if base_env is not None else dict(os.environ)
        self.records: list[dict[str, Any]] = []

    def env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = dict(self.base_env)
        if self.toolchain:
            env["RUSTUP_TOOLCHAIN"] = self.toolchain
        if extra:
            env.update(extra)
        return env

    def run(self, cmd: list[str], cwd: Path | str, *, timeout: float = 180.0,
            env_extra: dict[str, str] | None = None,
            offline: bool = False) -> ToolCall:
        cwd = Path(cwd).resolve()
        full_cmd = list(cmd)
        if offline and "--offline" not in full_cmd:
            full_cmd = [full_cmd[0], "--offline", *full_cmd[1:]]
        full_cmd = _absolutize_program(full_cmd)
        env = self.env(env_extra)
        started = time.monotonic()
        timed_out = False
        error: str | None = None
        returncode: int | None = None
        stdout = ""
        stderr = ""
        try:
            proc = self.runner(full_cmd, cwd, timeout, env)
            returncode = getattr(proc, "returncode", None)
            stdout = getattr(proc, "stdout", "") or ""
            stderr = getattr(proc, "stderr", "") or ""
        except subprocess.TimeoutExpired:
            timed_out = True
        except OSError as exc:  # missing binary, exec failure, ...
            error = str(exc)
        wall_ms = int((time.monotonic() - started) * 1000)
        self.records.append({
            "argv": full_cmd,
            "cwd": str(cwd),
            "env_keys": sorted(env.keys()),
            "returncode": returncode,
            "timed_out": timed_out,
            "stdout_sha256": _sha(stdout),
            "stderr_sha256": _sha(stderr),
            "wall_ms": wall_ms,
            "error": error,
        })
        return ToolCall(cmd=full_cmd, returncode=returncode, stdout=stdout,
                        stderr=stderr, wall_ms=wall_ms, timed_out=timed_out,
                        error=error)

    def archive(self) -> list[dict[str, Any]]:
        return list(self.records)


def cleanup_target(workdir: Path | str, *, keep: bool | None = None) -> bool:
    """Delete ``<workdir>/target`` unless ``SKELNET_KEEP_TARGET=1``.

    Returns True when the directory was removed.
    """
    import shutil
    if keep is None:
        keep = os.environ.get("SKELNET_KEEP_TARGET") == "1"
    if keep:
        return False
    target = Path(workdir) / "target"
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
        return True
    return False
