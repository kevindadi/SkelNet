"""External Rust evaluator shared by all arms.

Every arm's final Rust is scored by this one evaluator: build (std-only +
``concir_sync``), run, and check the task's required terminal line. A missing
terminal line is recorded as ``terminal_check: "absent"`` and is never counted
as a pass. Instrumentation / runtime monitoring is a best-effort fallback and is
not mixed into the code score. Tests inject :class:`FakeOracle` or a fake
``runner``; no network or LLM is involved.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

CONCIR_SYNC_CRATE = Path(__file__).resolve().parents[2] / "runtime/concir_sync"


def cargo_toml(name: str, *, bin_path: str = "src/main.rs") -> str:
    return f"""[package]
name = "{name}"
version = "0.1.0"
edition = "2021"

[[bin]]
name = "{name}"
path = "{bin_path}"

[dependencies]
concir_sync = {{ path = "{CONCIR_SYNC_CRATE}" }}
"""


@dataclass
class OracleResult:
    built: bool = False
    ran: bool = False
    functional_ok: bool = False
    monitor_ok: bool | None = None
    terminal_check: str = "absent"  # "pass" | "fail" | "absent"
    stdout: str = ""
    stderr: str = ""
    details: dict[str, Any] = field(default_factory=dict)


def _default_runner(cmd: list[str], cwd: Path, timeout: float):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout)


class RustOracle:
    def __init__(self, *, terminal: str | None = None, timeout: float = 180.0,
                 cargo: str = "cargo",
                 runner: Callable[[list[str], Path, float], Any] | None = None) -> None:
        self.terminal = terminal
        self.timeout = timeout
        self.cargo = cargo
        self.runner = runner or _default_runner

    def evaluate(self, rust_source: str, workdir: Path | str, *,
                 extra_files: dict[str, str] | None = None) -> OracleResult:
        workdir = Path(workdir)
        src = workdir / "src"
        src.mkdir(parents=True, exist_ok=True)
        (workdir / "Cargo.toml").write_text(cargo_toml("probe"), encoding="utf-8")
        (src / "main.rs").write_text(rust_source, encoding="utf-8")
        for rel, content in (extra_files or {}).items():
            target = workdir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        try:
            build = self.runner([self.cargo, "build", "--offline"], workdir, self.timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return OracleResult(built=False, stderr=str(exc))
        if build.returncode != 0:
            return OracleResult(built=False, stderr=build.stderr)
        try:
            run = self.runner([self.cargo, "run", "--offline", "--quiet"],
                              workdir, self.timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return OracleResult(built=True, ran=False, stderr=str(exc))
        ran_ok = run.returncode == 0
        if self.terminal is None:
            terminal_check = "absent"
        elif self.terminal in run.stdout:
            terminal_check = "pass"
        else:
            terminal_check = "fail"
        functional_ok = ran_ok and terminal_check == "pass"
        return OracleResult(built=True, ran=True, functional_ok=functional_ok,
                            terminal_check=terminal_check, stdout=run.stdout,
                            stderr=run.stderr)


class FakeOracle:
    """Deterministic oracle for offline tests."""

    def __init__(self, functional_ok: bool = True) -> None:
        self.functional_ok = functional_ok
        self.terminal_check = "pass" if functional_ok else "fail"
        self.calls: list[str] = []

    def evaluate(self, rust_source: str, workdir: Path | str, *,
                 extra_files: dict[str, str] | None = None) -> OracleResult:
        self.calls.append(rust_source)
        return OracleResult(built=True, ran=True, functional_ok=self.functional_ok,
                            terminal_check=self.terminal_check, stdout="DONE\n",
                            details={"fake": True,
                                     "extra_files": sorted((extra_files or {}).keys())})
