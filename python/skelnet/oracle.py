"""External Rust evaluator shared by all arms.

Every arm's final Rust is scored by this one evaluator: build (std-only +
``concir_sync``), run, and check the required terminal line. Instrumentation /
runtime monitoring is a best-effort fallback and is not mixed into the code
score. Tests inject :class:`FakeOracle`; no network or LLM is involved.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    stdout: str = ""
    stderr: str = ""
    details: dict[str, Any] = field(default_factory=dict)


class RustOracle:
    def __init__(self, *, terminal: str | None = None, timeout: float = 180.0,
                 cargo: str = "cargo") -> None:
        self.terminal = terminal
        self.timeout = timeout
        self.cargo = cargo

    def evaluate(self, rust_source: str, workdir: Path | str) -> OracleResult:
        workdir = Path(workdir)
        src = workdir / "src"
        src.mkdir(parents=True, exist_ok=True)
        (workdir / "Cargo.toml").write_text(cargo_toml("probe"), encoding="utf-8")
        (src / "main.rs").write_text(rust_source, encoding="utf-8")
        try:
            build = subprocess.run([self.cargo, "build", "--offline"],
                                   cwd=workdir, capture_output=True, text=True,
                                   timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return OracleResult(built=False, stderr=str(exc))
        if build.returncode != 0:
            return OracleResult(built=False, stderr=build.stderr)
        try:
            run = subprocess.run([self.cargo, "run", "--offline", "--quiet"],
                                 cwd=workdir, capture_output=True, text=True,
                                 timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return OracleResult(built=True, ran=False, stderr=str(exc))
        ok = run.returncode == 0
        if self.terminal is not None:
            ok = ok and self.terminal in run.stdout
        return OracleResult(built=True, ran=True, functional_ok=ok,
                            stdout=run.stdout, stderr=run.stderr)


class FakeOracle:
    """Deterministic oracle for offline tests."""

    def __init__(self, functional_ok: bool = True) -> None:
        self.functional_ok = functional_ok
        self.calls: list[str] = []

    def evaluate(self, rust_source: str, workdir: Path | str) -> OracleResult:
        self.calls.append(rust_source)
        return OracleResult(built=True, ran=True, functional_ok=self.functional_ok,
                            stdout="DONE\n", details={"fake": True})
