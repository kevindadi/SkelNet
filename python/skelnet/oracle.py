"""Independent four-layer Rust oracle (round 3), shared by all arms.

O1 build + policy, O2 termination/output, O3 schedule exploration (Shuttle +
miri), O4 structural fidelity (instrumentation + runtime monitor). The layers
are arm-agnostic: every experimental group's final Rust is scored the same way.

Tests inject :class:`FakeOracle` or a fake ``runner``; no network or LLM is
involved. Real runs resolve the tool binaries through ``backend.find_binary``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .backend import find_binary, repo_root
from .rusttools import base as layers_mod
from .rusttools.base import FAIL, NOT_RUN, PASS, UNAVAILABLE, UNSUPPORTED, LayerResult
from .rusttools.miri import evaluate_miri
from .rusttools.monitor import evaluate_o4
from .rusttools.policy import evaluate_o1
from .rusttools.runner import ToolRunner, cleanup_target
from .rusttools.seeds import (ORACLE_MIRI_SEED_COUNT, ORACLE_MIRI_SEED_START,
                              ORACLE_SHUTTLE_SEED)
from .rusttools.shuttle import evaluate_shuttle
from .rusttools.stress import evaluate_o2

CONCIR_SYNC_CRATE = Path(__file__).resolve().parents[2] / "runtime/concir_sync"
SHUTTLE_SHIM_CRATE = Path(__file__).resolve().parents[2] / "tools/concir_sync_shuttle"

_DEFAULT_LAYERS = ("O1", "O2", "O3", "O4")


def repo_toolchain_channel() -> str | None:
    """The `channel` from the repository's rust-toolchain.toml, or None.

    rustup resolves a toolchain relative to the working directory, so a cargo
    run outside the repo would otherwise pick up the default toolchain. The
    oracle pins `RUSTUP_TOOLCHAIN` to this value explicitly.
    """
    path = Path(__file__).resolve().parents[2] / "rust-toolchain.toml"
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("channel"):
            _, _, value = stripped.partition("=")
            value = value.strip().strip('"').strip("'")
            return value or None
    return None


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

[workspace]
"""


def _tool_path(name: str, env_var: str) -> str:
    """Locate a workspace tool, falling back to the bare name.

    The bare name is returned when the tool is absent so an injected runner can
    still observe (and stub) the call; the real runner then reports the missing
    binary as ``unavailable``.
    """
    try:
        return str(find_binary(name, env_var=env_var))
    except FileNotFoundError:
        return name


@dataclass
class OracleResult:
    built: bool = False
    ran: bool = False
    # run_ok: the program exited 0 and did not time out / panic (every mode).
    run_ok: bool = False
    # functional_ok is None when a layer is unavailable or terminal is unchecked.
    functional_ok: bool | None = None
    functional_ok_no_o4: bool | None = None
    monitor_ok: bool | None = None
    # "pass" | "fail" | "absent" | "not_applicable" | "not_run"
    terminal_check: str = "not_run"
    # True only when every layer actually ran and decided.
    oracle_complete: bool = False
    stdout: str = ""
    stderr: str = ""
    layers: dict[str, LayerResult] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)


def _o3_tools(result: OracleResult) -> dict[str, Any] | None:
    """The Shuttle/miri sub-results recorded on the O3 layer's data (round 8).

    ``_combine_o3`` stores the two half-layer dicts (and the ``no_concurrency``
    marker) in the combined O3 layer's ``data``.  Without O3, or before it ran,
    there is nothing to report.
    """
    layer = result.layers.get("O3")
    data = getattr(layer, "data", None) if layer is not None else None
    if not isinstance(data, dict) or "shuttle" not in data or "miri" not in data:
        return None

    def pair(name: str) -> dict[str, Any]:
        sub = data.get(name) or {}
        return {"status": sub.get("status"), "category": sub.get("category")}

    return {"shuttle": pair("shuttle"), "miri": pair("miri"),
            "no_concurrency": bool(data.get("no_concurrency"))}


def oracle_result_dict(result: OracleResult) -> dict[str, Any]:
    """The frozen ``oracle`` sub-dict shared with the cell schema."""
    return {
        "built": result.built,
        "ran": result.ran,
        "run_ok": result.run_ok,
        "functional_ok": result.functional_ok,
        "functional_ok_no_o4": result.functional_ok_no_o4,
        "terminal_check": result.terminal_check,
        "oracle_complete": result.oracle_complete,
        "layers": {name: layer.to_dict() for name, layer in result.layers.items()},
        "o3_tools": _o3_tools(result),
    }


def _default_runner(cmd: list[str], cwd: Path, timeout: float, env: dict[str, str]):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout, env=env)


def _participates(layer: LayerResult | None) -> bool:
    return layer is not None and layer.status in (PASS, FAIL)


def _conjunction(layers: dict[str, LayerResult], names: tuple[str, ...]) -> bool | None:
    relevant = [layers[name] for name in names if name in layers]
    if any(layer.status == UNAVAILABLE for layer in relevant):
        return None
    participating = [layer for layer in relevant if _participates(layer)]
    if not participating:
        return None
    return all(layer.status == PASS for layer in participating)


def _complete(layers: dict[str, LayerResult]) -> bool:
    for layer in layers.values():
        if layer.status not in (PASS, FAIL):
            return False
        if layer.data.get("complete") is False:
            return False
    return True


def _combine_o3(shuttle: LayerResult, miri: LayerResult) -> LayerResult:
    started_wall = (shuttle.wall_ms or 0) + (miri.wall_ms or 0)
    data = {"shuttle": {**shuttle.to_dict(), **shuttle.data},
            "miri": {**miri.to_dict(), **miri.data}, "complete": True}
    no_concurrency = bool(shuttle.data.get("no_concurrency"))
    if no_concurrency:
        # Promote the marker to the O3 layer so calibration can list it.
        data["no_concurrency"] = True

    def finish(status: str, category: str | None,
               detail: str | None) -> LayerResult:
        if no_concurrency and "no concurrency to explore" not in (detail or ""):
            detail = (detail + "; " if detail else "") + "no concurrency to explore"
        return LayerResult("O3", status, category, detail, started_wall, data)

    if shuttle.status == UNAVAILABLE and miri.status == UNAVAILABLE:
        return finish(UNAVAILABLE, "tools_unavailable",
                      "shuttle and miri both unavailable")

    deciding = [(name, layer) for name, layer in (("shuttle", shuttle), ("miri", miri))
                if layer.status in (PASS, FAIL)]
    skipped = [(name, layer) for name, layer in (("shuttle", shuttle), ("miri", miri))
               if layer.status in (UNSUPPORTED, UNAVAILABLE)]
    if skipped:
        data["complete"] = False
    if not deciding:
        # Both halves are unsupported, or one is unsupported and the other
        # unavailable: no half could decide the conjunction.
        categories = [layer.category for _, layer in skipped if layer.category]
        if all(layer.status == UNSUPPORTED for _, layer in skipped):
            return finish(UNSUPPORTED,
                          categories[0] if categories else "unsupported",
                          "shuttle and miri both unsupported")
        return finish(UNAVAILABLE,
                      categories[0] if categories else "tools_unavailable",
                      "no half could decide")
    for name, layer in deciding:
        if layer.status == FAIL:
            detail = layer.detail
            if skipped:
                detail = f"{skipped[0][0]} skipped; {name}: {detail}"
            return finish(FAIL, layer.category, detail)
    category = skipped[0][1].category if skipped else None
    detail = "; ".join(f"{name} {layer.status}" for name, layer in skipped) or None
    return finish(PASS, category, detail)


class RustOracle:
    def __init__(self, *, terminal: str | None = None, timeout: float = 180.0,
                 cargo: str = "cargo",
                 runner: Callable[[list[str], Path, float, dict], Any] | None = None,
                 toolchain: str | None = None,
                 task_dir: Path | str | None = None,
                 layers: tuple[str, ...] | list[str] | None = None,
                 stress_runs: int = 20, stress_timeout: float = 10.0,
                 shuttle_iterations: int = 2000, shuttle_depth: int = 3,
                 miri_seed_start: int = ORACLE_MIRI_SEED_START,
                 miri_seed_count: int = ORACLE_MIRI_SEED_COUNT,
                 monitor_runs: int = 5) -> None:
        self.terminal = terminal
        self.timeout = timeout
        self.cargo = cargo
        self.runner = runner or _default_runner
        self.toolchain = toolchain if toolchain is not None else repo_toolchain_channel()
        self.task_dir = Path(task_dir) if task_dir is not None else None
        self.layers = tuple(layers) if layers is not None else _DEFAULT_LAYERS
        self.stress_runs = stress_runs
        self.stress_timeout = stress_timeout
        self.shuttle_iterations = shuttle_iterations
        self.shuttle_depth = shuttle_depth
        self.miri_seed_start = miri_seed_start
        self.miri_seed_count = miri_seed_count
        self.monitor_runs = monitor_runs
        self.instrument_bin = _tool_path("concir-instrument", "CONCIR_INSTRUMENT")
        self.backend_bin = _tool_path("concir-backend", "CONCIR_BACKEND")
        self.tools: ToolRunner | None = None

    # ── layer runners ────────────────────────────────────────────────
    def _o3(self, tools: ToolRunner, workdir: Path, src: str, *,
            check_terminal: bool = True) -> LayerResult:
        if "O3" not in self.layers:
            return LayerResult("O3", NOT_RUN, "disabled", "O3 disabled")
        # Every explored Shuttle schedule must end with the terminal line,
        # as every O2 run must (round 9b). Codegen mode checks no terminal.
        shuttle = evaluate_shuttle(
            tools, workdir, src, shim_path=SHUTTLE_SHIM_CRATE,
            iterations=self.shuttle_iterations, depth=self.shuttle_depth,
            seed=ORACLE_SHUTTLE_SEED, timeout=self.timeout, cargo=self.cargo,
            terminal=self.terminal if check_terminal else None)
        miri = evaluate_miri(
            tools, workdir, seed_start=self.miri_seed_start,
            seed_count=self.miri_seed_count, timeout=self.timeout, cargo=self.cargo)
        return _combine_o3(shuttle, miri)

    def _o4(self, tools: ToolRunner, workdir: Path, src: str) -> LayerResult:
        if "O4" not in self.layers:
            return LayerResult("O4", NOT_RUN, "disabled", "O4 disabled")
        return evaluate_o4(
            tools, workdir, src, task_dir=self.task_dir,
            instrument_bin=self.instrument_bin, backend_bin=self.backend_bin,
            concir_sync_path=CONCIR_SYNC_CRATE, runs=self.monitor_runs,
            timeout=self.timeout, cargo=self.cargo)

    def evaluate(self, rust_source: str, workdir: Path | str, *,
                 extra_files: dict[str, str] | None = None,
                 check_terminal: bool = True) -> OracleResult:
        workdir = Path(workdir)
        src = workdir / "src"
        src.mkdir(parents=True, exist_ok=True)
        (workdir / "Cargo.toml").write_text(cargo_toml("probe"), encoding="utf-8")
        (src / "main.rs").write_text(rust_source, encoding="utf-8")
        for rel, content in (extra_files or {}).items():
            target = workdir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        tools = ToolRunner(runner=self.runner, toolchain=self.toolchain)
        self.tools = tools
        layers: dict[str, LayerResult] = {}

        o1 = evaluate_o1(tools, workdir, rust_source, timeout=self.timeout,
                         cargo=self.cargo)
        layers["O1"] = o1
        if o1.status in (FAIL, UNAVAILABLE):
            reason = "O1 did not pass" if o1.status == FAIL else "O1 unavailable"
            for name in ("O2", "O3", "O4"):
                layers[name] = LayerResult(name, NOT_RUN, None, reason)
            result = self._finish(workdir, layers, check_terminal, o1, None)
            return result

        binary = workdir / "target" / "debug" / "probe"
        o2 = evaluate_o2(tools, binary, terminal=self.terminal,
                         runs=self.stress_runs, run_timeout=self.stress_timeout,
                         check_terminal=check_terminal)
        layers["O2"] = o2
        layers["O3"] = self._o3(tools, workdir, rust_source,
                                check_terminal=check_terminal)
        if o2.category in ("hang", "crash"):
            # A program that hangs/crashes cannot be instrumented meaningfully;
            # O4 depends on O2's termination.
            layers["O4"] = LayerResult("O4", NOT_RUN, None, f"O2 {o2.category}")
        else:
            layers["O4"] = self._o4(tools, workdir, rust_source)
        result = self._finish(workdir, layers, check_terminal, o1, o2)
        return result

    def _finish(self, workdir: Path, layers: dict[str, LayerResult],
                check_terminal: bool, o1: LayerResult,
                o2: LayerResult | None) -> OracleResult:
        functional = _conjunction(layers, self.layers)
        no_o4 = _conjunction(layers, tuple(n for n in self.layers if n != "O4"))
        if not check_terminal:
            # Deterministic codegen has no task-specific terminal line: neither
            # the main metric nor the sensitivity metric is defined.
            functional = None
            no_o4 = None
        if o2 is None:
            terminal_check = "not_run"
        else:
            terminal_check = o2.data.get("terminal_check", "not_run")
        built = o1.status == PASS
        ran = bool(o2 is not None and o2.data.get("ran"))
        run_ok = bool(o2 is not None and o2.data.get("run_ok"))
        details = {"tool_calls": self.tools.archive() if self.tools else []}
        result = OracleResult(
            built=built, ran=ran, run_ok=run_ok, functional_ok=functional,
            functional_ok_no_o4=no_o4, terminal_check=terminal_check,
            oracle_complete=_complete(layers), stdout="", stderr="",
            layers=layers, details=details)
        self._cleanup(workdir)
        return result

    @staticmethod
    def _cleanup(workdir: Path) -> None:
        if os.environ.get("SKELNET_KEEP_TARGET") == "1":
            return
        for target in (workdir / "target", workdir / "shuttle" / "target",
                       workdir / "o4" / "project" / "target"):
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
        cleanup_target(workdir)


class FakeOracle:
    """Deterministic oracle for offline tests."""

    def __init__(self, functional_ok: bool = True) -> None:
        self.functional_ok = functional_ok
        self.terminal_check = "pass" if functional_ok else "fail"
        self.calls: list[str] = []

    def evaluate(self, rust_source: str, workdir: Path | str, *,
                 extra_files: dict[str, str] | None = None,
                 check_terminal: bool = True) -> OracleResult:
        self.calls.append(rust_source)
        if check_terminal:
            terminal_check = "pass" if self.functional_ok else "fail"
            functional_ok = self.functional_ok
        else:
            terminal_check = "not_applicable"
            functional_ok = None
        return OracleResult(
            built=True, ran=True, run_ok=True, functional_ok=functional_ok,
            functional_ok_no_o4=functional_ok, terminal_check=terminal_check,
            oracle_complete=True, stdout="DONE\n",
            details={"fake": True,
                     "extra_files": sorted((extra_files or {}).keys())})
