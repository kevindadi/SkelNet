"""Backend wrapper: run the ``skelnet`` / ``concir-backend`` binaries.

Never shells out to a real LLM. Every invocation archives its exit code and
output; input hashes are recorded so a result is bound to its artifact.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BackendResult:
    kind: str  # "semantic" | "process"
    status: str  # "ok" | "invalid" | "unsupported" | "unknown" | "fail" | "process_error"
    outcome: str | None = None
    complete: bool | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.kind == "semantic" and self.status == "ok"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _candidates(name: str) -> list[Path]:
    root = repo_root()
    return [root / "target" / "debug" / name, root / "target" / "release" / name]


def find_binary(name: str, explicit: str | Path | None = None,
                env_var: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    if env_var and os.environ.get(env_var):
        return Path(os.environ[env_var]).expanduser().resolve()
    for candidate in _candidates(name):
        if candidate.is_file():
            return candidate
    found = shutil.which(name)
    if found:
        return Path(found)
    raise FileNotFoundError(
        f"{name} not found; build the workspace (`cargo build`) or set {env_var}")


def sha256_file(path: Path | str) -> str | None:
    p = Path(path)
    if not p.is_file():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()


class BackendTimeout(RuntimeError):
    """The backend subprocess exceeded its timeout."""

    def __init__(self, timeout: float) -> None:
        super().__init__(f"backend timeout after {timeout}s")
        self.timeout = timeout


def _run(cmd: list[str], *, cwd: Path | None = None, timeout: float = 300.0) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise BackendTimeout(timeout) from exc


def _timeout_result(timeout: float) -> "BackendResult":
    return BackendResult("process", "timeout",
                         error=f"backend timeout after {timeout}s")


class Backend:
    def __init__(self, *, skelnet: str | Path | None = None,
                 concir: str | Path | None = None, timeout: float = 300.0) -> None:
        self.skelnet = find_binary("skelnet", skelnet, "SKELNET_BIN")
        self.concir = find_binary("concir-backend", concir, "CONCIR_BACKEND")
        self.timeout = timeout

    # ── skeleton ─────────────────────────────────────────────────────
    def check(self, skel: Path | str, *, reqs: Path | str | None = None) -> BackendResult:
        args = [str(self.skelnet), "check", str(skel), "--json"]
        if reqs:
            args += ["--reqs", str(reqs)]
        try:
            proc = _run(args, timeout=self.timeout)
        except (BackendTimeout, subprocess.TimeoutExpired):
            return _timeout_result(self.timeout)
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return BackendResult("process", "process_error", error=proc.stderr.strip(),
                                 exit_code=proc.returncode, stdout=proc.stdout,
                                 stderr=proc.stderr)
        valid = bool(payload.get("valid"))
        return BackendResult(
            "semantic", "ok" if valid else "invalid",
            payload=payload, exit_code=proc.returncode,
            stdout=proc.stdout, stderr=proc.stderr,
            error=None if valid else (payload.get("support_error") or "invalid"),
        )

    def verify(self, skel: Path | str, contract: Path | str, *,
               engine: str = "petri") -> BackendResult:
        args = [str(self.skelnet), "verify", str(skel), str(contract),
                "--engine", engine, "--json"]
        try:
            proc = _run(args, timeout=self.timeout)
        except (BackendTimeout, subprocess.TimeoutExpired):
            return _timeout_result(self.timeout)
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return BackendResult("process", "process_error", error=proc.stderr.strip(),
                                 exit_code=proc.returncode, stdout=proc.stdout,
                                 stderr=proc.stderr)
        outcome = payload.get("outcome")
        return BackendResult(
            "semantic", _status_for(outcome), outcome=outcome,
            complete=payload.get("complete"), payload=payload,
            exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr,
        )

    def lower(self, skel: Path | str, out: Path | str, *, map_path: Path | str | None = None) -> BackendResult:
        args = [str(self.skelnet), "lower", str(skel), "-o", str(out)]
        if map_path:
            args += ["--map", str(map_path)]
        try:
            proc = _run(args, timeout=self.timeout)
        except (BackendTimeout, subprocess.TimeoutExpired):
            return _timeout_result(self.timeout)
        status = "ok" if proc.returncode == 0 else "invalid"
        return BackendResult("semantic", status, exit_code=proc.returncode,
                             stdout=proc.stdout, stderr=proc.stderr,
                             error=None if proc.returncode == 0 else proc.stderr.strip())

    # ── deterministic codegen (fallback Rust) ────────────────────────
    def codegen_skel(self, skel: Path | str, out_dir: Path | str) -> "CodegenResult":
        return self._codegen([str(self.skelnet), "codegen", str(skel),
                              "--out", str(out_dir)], out_dir)

    def codegen_cir(self, cir: Path | str, out_dir: Path | str) -> "CodegenResult":
        return self._codegen([str(self.concir), "codegen", str(cir),
                              "--out", str(out_dir)], out_dir)

    def _codegen(self, args: list[str], out_dir: Path | str) -> "CodegenResult":
        out_dir = Path(out_dir)
        try:
            proc = _run(args, timeout=self.timeout)
        except (BackendTimeout, subprocess.TimeoutExpired):
            return CodegenResult(ok=False,
                                 error=f"backend timeout after {self.timeout}s")
        if proc.returncode != 0:
            return CodegenResult(ok=False, error=proc.stderr.strip() or proc.stdout.strip())
        main_rs = out_dir / "src" / "main.rs"
        trace_rs = out_dir / "src" / "cir_trace.rs"
        if not main_rs.exists():
            return CodegenResult(ok=False, error="codegen produced no src/main.rs")
        return CodegenResult(
            ok=True,
            main_rs=main_rs.read_text(encoding="utf-8"),
            trace_rs=trace_rs.read_text(encoding="utf-8") if trace_rs.exists() else "",
        )

    # ── ConcIR (CIR arm) ─────────────────────────────────────────────
    def verify_cir(self, cir: Path | str, contract: Path | str, *,
                   engine: str = "petri") -> BackendResult:
        args = [str(self.concir), "explore", str(cir), str(contract), engine]
        try:
            proc = _run(args, timeout=self.timeout)
        except (BackendTimeout, subprocess.TimeoutExpired):
            return _timeout_result(self.timeout)
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return BackendResult("process", "process_error", error=proc.stderr.strip(),
                                 exit_code=proc.returncode, stdout=proc.stdout,
                                 stderr=proc.stderr)
        outcome = payload.get("outcome")
        return BackendResult("semantic", _status_for(outcome), outcome=outcome,
                             complete=payload.get("complete"), payload=payload,
                             exit_code=proc.returncode, stdout=proc.stdout,
                             stderr=proc.stderr)


@dataclass
class CodegenResult:
    ok: bool
    main_rs: str = ""
    trace_rs: str = ""
    error: str | None = None


def _status_for(outcome: str | None) -> str:
    return {
        "PASS": "ok", "FAIL": "fail", "UNKNOWN": "unknown",
        "INVALID": "invalid", "UNSUPPORTED": "unsupported",
    }.get(outcome or "", "process_error")
