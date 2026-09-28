"""Shared helpers for the round-3 oracle tests.

The ``rust_tools`` marker skips tests that need real cargo / miri / Shuttle and
prints why. Availability is probed with the repository's pinned toolchain
(``cargo miri --version``), not ``shutil.which("miri")``: a standard rustup
install has no ``miri`` proxy, only ``cargo-miri``. :class:`FakeTools` is a
runner that stands in for the outermost subprocess only; the oracle's layer
logic is always exercised.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _toolchain() -> str | None:
    from skelnet.oracle import repo_toolchain_channel
    return repo_toolchain_channel()


def _shuttle_available() -> bool:
    cargo_home = Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo"))
    for src in (cargo_home / "registry" / "src").glob("*/shuttle-0.8.1"):
        if src.is_dir():
            return True
    return False


def _concir_binary(name: str, env_var: str) -> bool:
    if os.environ.get(env_var):
        return True
    root = _repo_root()
    return any((root / "target" / profile / name).is_file()
               for profile in ("debug", "release"))


_AVAIL_CACHE: dict[str, bool] = {}


def _check(cmd: list[str], runner=None) -> bool:
    """Run ``cmd --version``; a runner may be injected for tests."""
    key = " ".join(cmd)
    if runner is None and key in _AVAIL_CACHE:
        return _AVAIL_CACHE[key]
    run = runner or subprocess.run
    env = dict(os.environ)
    toolchain = _toolchain()
    if toolchain:
        env["RUSTUP_TOOLCHAIN"] = toolchain
    try:
        proc = run(cmd, capture_output=True, text=True, timeout=120, env=env)
        result = getattr(proc, "returncode", 1) == 0
    except Exception:  # noqa: BLE001 - any failure means "not available"
        result = False
    if runner is None:
        _AVAIL_CACHE[key] = result
    return result


def cargo_available(runner=None) -> bool:
    return _check(["cargo", "--version"], runner)


def miri_available(runner=None) -> bool:
    return _check(["cargo", "miri", "--version"], runner)


def rust_tools_available(runner=None) -> bool:
    return bool(cargo_available(runner) and miri_available(runner)
                and _shuttle_available()
                and _concir_binary("concir-instrument", "CONCIR_INSTRUMENT")
                and _concir_binary("concir-backend", "CONCIR_BACKEND"))


def _reason() -> str:
    missing = []
    if not cargo_available():
        missing.append("cargo")
    if not miri_available():
        missing.append("cargo miri (run scripts/setup_oracle_tools.sh)")
    if not _shuttle_available():
        missing.append("shuttle-0.8.1 (run scripts/setup_oracle_tools.sh)")
    if not _concir_binary("concir-instrument", "CONCIR_INSTRUMENT"):
        missing.append("concir-instrument (run cargo build --workspace)")
    if not _concir_binary("concir-backend", "CONCIR_BACKEND"):
        missing.append("concir-backend (run cargo build --workspace)")
    return "missing rust tools: " + ", ".join(missing)


# Real cargo / miri / Shuttle / concir binaries.
rust_tools = pytest.mark.skipif(not rust_tools_available(), reason=_reason())
# Only real cargo is needed (O1 build / workspace tests).
cargo_only = pytest.mark.skipif(not cargo_available(), reason=_reason())


def ns(returncode: int, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _package_name(cwd: Path) -> str | None:
    manifest = cwd / "Cargo.toml"
    if not manifest.exists():
        return None
    match = re.search(r'name\s*=\s*"([^"]+)"', manifest.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def _make_binary(cwd: Path) -> None:
    name = _package_name(cwd)
    if name is None:
        return
    binary = cwd / "target" / "debug" / name
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)


class FakeTools:
    """A configurable stand-in for the whole external tool suite."""

    def __init__(self, *, terminal: str = "DONE t1=1 t2=1",
                 resources: list[dict] | None = None,
                 monitor_report: dict | None = None,
                 o2_stdout: str | None = None, build_ok: bool = True,
                 instrument_ok: bool = True, miri_output: str = "",
                 miri_rc: int = 0, shuttle_deadlock: bool = False,
                 shuttle_rc: int = 0, shuttle_output: str = "",
                 annotated: str | None = None,
                 traces: list[list[dict]] | None = None,
                 o2_hang: bool = False,
                 instrument_writes: bool = True, on_build=None) -> None:
        self.terminal = terminal
        self.resources = resources if resources is not None else DEFAULT_RESOURCES
        self.monitor_report = monitor_report if monitor_report is not None else DEFAULT_REPORT
        self.o2_stdout = o2_stdout if o2_stdout is not None else terminal + "\n"
        self.build_ok = build_ok
        self.instrument_ok = instrument_ok
        self.miri_output = miri_output
        self.miri_rc = miri_rc
        self.shuttle_deadlock = shuttle_deadlock
        self.shuttle_rc = shuttle_rc
        self.shuttle_output = shuttle_output
        self.annotated = annotated
        self.traces = traces if traces is not None else [DEFAULT_TRACE]
        self.o2_hang = o2_hang
        self.instrument_writes = instrument_writes
        self.on_build = on_build
        self.calls: list[list[str]] = []
        self.envs: list[dict] = []
        self.builds: list[Path] = []
        self._run_index = 0

    def __call__(self, cmd, cwd, timeout, env):
        cmd = [str(part) for part in cmd]
        cwd = Path(cwd)
        self.calls.append(list(cmd))
        self.envs.append(dict(env))
        name = Path(cmd[0]).name
        if name == "concir-instrument":
            return self._instrument(cmd)
        if name == "concir-backend":
            return ns(0, json.dumps(self.monitor_report), "")
        if "miri" in cmd:
            return ns(self.miri_rc, self.miri_output, self.miri_output)
        if "build" in cmd:
            self.builds.append(cwd)
            if self.on_build is not None:
                self.on_build(cwd)
            if not self.build_ok:
                return ns(1, "", "error[E0001]: build failed")
            _make_binary(cwd)
            return ns(0, "", "")
        if name.endswith("shuttle_probe"):
            if self.shuttle_deadlock:
                return ns(1, "", "deadlock! blocked tasks: [main, t1, t2]")
            return ns(self.shuttle_rc, self.shuttle_output, self.shuttle_output)
        # A program run: write the trace the instrumented runtime would.
        trace_out = env.get("CIR_TRACE_OUT")
        if trace_out:
            trace = self.traces[min(self._run_index, len(self.traces) - 1)]
            self._run_index += 1
            Path(trace_out).write_text(
                "\n".join(json.dumps(event) for event in trace) + "\n",
                encoding="utf-8")
        elif self.o2_hang:
            raise subprocess.TimeoutExpired(cmd, timeout)
        return ns(0, self.o2_stdout, "")

    def _instrument(self, cmd):
        if not self.instrument_ok:
            return ns(1, "", "instrument v2 failed: parse error")
        out = Path(cmd[cmd.index("--out") + 1])
        out.mkdir(parents=True, exist_ok=True)
        if self.instrument_writes:
            annotated = self.annotated or (
                "mod cir_trace;\nfn main() { cir_trace::init(); cir_trace::finish(); }\n")
            (out / "annotated.rs").write_text(annotated, encoding="utf-8")
            (out / "cir_trace.rs").write_text("// generated runtime\n", encoding="utf-8")
        (out / "resources.json").write_text(
            json.dumps({"schema_version": "cir-resources-v1",
                        "resources": self.resources}), encoding="utf-8")
        return ns(0, json.dumps({"mode": "wrappers"}), "")


# The measured instrumented names for the abba fixture (task statement).
DEFAULT_RESOURCES = [
    {"name": "a_mutex0#86", "kind": "Mutex", "display": "a_mutex0"},
    {"name": "b_mutex0#124", "kind": "Mutex", "display": "b_mutex0"},
    {"name": "t1#200", "kind": "Spawn", "display": "t1"},
    {"name": "t2#354", "kind": "Spawn", "display": "t2"},
]

# A trace where t1 and t2 each hold a and b at once.
DEFAULT_TRACE = [
    {"t": "t0", "sid": "s1", "op": "spawn", "r": "t1#200"},
    {"t": "t0", "sid": "s2", "op": "spawn", "r": "t2#354"},
    {"t": "t1", "sid": "s3", "op": "mutex_lock", "r": "a_mutex0#86"},
    {"t": "t1", "sid": "s4", "op": "mutex_lock", "r": "b_mutex0#124"},
    {"t": "t1", "sid": "s5", "op": "mutex_unlock", "r": "b_mutex0#124"},
    {"t": "t1", "sid": "s6", "op": "mutex_unlock", "r": "a_mutex0#86"},
    {"t": "t2", "sid": "s7", "op": "mutex_lock", "r": "a_mutex0#86"},
    {"t": "t2", "sid": "s8", "op": "mutex_lock", "r": "b_mutex0#124"},
    {"t": "t2", "sid": "s9", "op": "mutex_unlock", "r": "b_mutex0#124"},
    {"t": "t2", "sid": "s10", "op": "mutex_unlock", "r": "a_mutex0#86"},
]

# A trace with no worker tags and no spawn events.
EMPTY_TRACE: list[dict] = [
    {"t": "t0", "sid": "s1", "op": "mutex_lock", "r": "a_mutex0#86"},
    {"t": "t0", "sid": "s2", "op": "mutex_unlock", "r": "a_mutex0#86"},
]

DEFAULT_REPORT = {
    "status": "ok",
    "bounded": True,
    "traces": 1,
    "events": len(DEFAULT_TRACE),
    "resource_map": {"a_mutex0#86": "main::a", "b_mutex0#124": "main::b",
                     "t1#200": "main::t1", "t2#354": "main::t2"},
    "unmapped_resources": [],
    "properties": [
        {"id": "no-deadlock", "kind": "deadlock_free", "source": "properties",
         "status": "deferred", "detail": None},
        {"id": "t1-completes", "kind": "reachable", "source": "preserved",
         "status": "PASS_bounded", "detail": None},
        {"id": "t2-completes", "kind": "reachable", "source": "preserved",
         "status": "PASS_bounded", "detail": None},
        {"id": "t1-holds", "kind": "reachable", "source": "preserved",
         "status": "PASS_bounded", "detail": None},
        {"id": "t2-holds", "kind": "reachable", "source": "preserved",
         "status": "PASS_bounded", "detail": None},
    ],
}
