"""A12: tool wall times are recorded and schema-checked."""

import json
from types import SimpleNamespace

from skelnet import cli
from skelnet.backend import Backend, BackendResult
from skelnet.oracle import FakeOracle
from skelnet.schema import validate_cell

TERMINAL = "DONE t1=1 t2=1"
RUST = f"```rust\nfn main() {{ println!(\"{TERMINAL}\"); }}\n```"
SKEL = "```skel\nskeleton t;\nfn main() {}\n```"
CIR = "```json\n{\"modules\": []}\n```"


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class _Runner:
    def __init__(self, clock):
        self.clock = clock

    def __call__(self, cmd, cwd, timeout, env):
        cmd = [str(part) for part in cmd]
        if env.get("RUSTC_WRAPPER"):
            self.clock.advance(3.0)
        elif "clippy" in cmd:
            self.clock.advance(2.0)
        elif "build" in cmd:
            self.clock.advance(1.0)
        return SimpleNamespace(returncode=0, stdout="", stderr="Possible bugs: conflictlock 0\n")


def _run(tmp_path, monkeypatch, clock, arm, replies, name):
    class Client:
        def __init__(self):
            self.n = 0
            self.replies = list(replies)

        def complete(self, system, user):
            self.n += 1
            text = self.replies[self.n - 1]
            return SimpleNamespace(
                text=text, usage=None, requested_model="deepseek-v4-flash",
                response_model=None, request_id="r",
                transport_attempt=1, cost=None, finish_reason="stop")

    out = tmp_path / name
    args = cli.build_parser().parse_args([
        "run", "--arm", arm, "--tasks", "lock-order/abba_2lock",
        "--reps", "1", "--rounds", "2", "--call-budget", "5",
        "--out", str(out), "--allow-missing-tools",
        "--budget-file", str(tmp_path / f"budget-{name}.json"),
    ])
    rc = cli.cmd_run(args, client_factory=lambda spec, _o: Client(),
                     oracle_runner=_Runner(clock),
                     oracle_factory=lambda _t, _term: FakeOracle(True))
    assert rc == 0, name
    return json.loads((out / "cells" / "lock-order" / "abba_2lock" / "0" / "result.json").read_text())


def test_cmd_run_records_injected_wall_times(tmp_path, monkeypatch):
    clock = _Clock()
    monkeypatch.setattr("time.monotonic", clock)
    stub = tmp_path / "lockbud-stub"
    stub.write_bytes(b"")
    monkeypatch.setenv("LOCKBUD_BIN", str(stub))
    checks = {"n": 0}

    def check(self, path, **kwargs):
        clock.advance(4.0)
        checks["n"] += 1
        if checks["n"] == 1:
            return BackendResult("semantic", "invalid", payload={"diagnostics": []})
        return BackendResult("semantic", "ok", payload={"diagnostics": []})

    def verify(self, path, contract, **kwargs):
        clock.advance(5.0)
        return BackendResult("semantic", "ok", outcome="PASS", complete=True,
                             payload={"properties": [], "unmapped": 0})

    def verify_cir(self, cir, contract, **kwargs):
        clock.advance(6.0)
        return BackendResult("semantic", "ok", outcome="PASS", complete=True,
                             payload={"properties": []})

    monkeypatch.setattr(Backend, "check", check)
    monkeypatch.setattr(Backend, "verify", verify)
    monkeypatch.setattr(Backend, "verify_cir", verify_cir)

    g0 = _run(tmp_path, monkeypatch, clock, "G0", [RUST], "g0")
    assert g0["compile_wall_ms"] == 1000
    assert isinstance(g0["compile_wall_ms"], int)

    static = _run(tmp_path, monkeypatch, clock, "STATIC", [RUST], "static")
    tools = static["baseline"]["rounds"][0]["tools"]
    assert static["baseline"]["rounds"][0]["compile_wall_ms"] == 1000
    assert tools["clippy"]["wall_ms"] == 2000
    assert tools["lockbud"]["wall_ms"] == 3000

    skel = _run(tmp_path, monkeypatch, clock, "SKEL", [SKEL, SKEL, RUST], "skel")
    assert skel["history"][0]["stage"] == "check"
    assert skel["history"][0]["wall_ms"] == 4000
    assert skel["history"][1]["stage"] == "verify"
    assert skel["history"][1]["wall_ms"] == 5000
    assert skel["rust_attempts"][-1]["compile_wall_ms"] == 1000

    cir = _run(tmp_path, monkeypatch, clock, "CIR", [CIR, RUST], "cir")
    assert cir["history"][0]["stage"] == "verify"
    assert cir["history"][0]["wall_ms"] == 6000
    assert cir["rust_attempts"][-1]["compile_wall_ms"] == 1000


def test_schema_rejects_string_timing(tmp_path, monkeypatch):
    clock = _Clock()
    monkeypatch.setattr("time.monotonic", clock)
    stub = tmp_path / "lockbud-stub"
    stub.write_bytes(b"")
    monkeypatch.setenv("LOCKBUD_BIN", str(stub))
    monkeypatch.setattr(Backend, "check", lambda self, path, **k: BackendResult("semantic", "invalid"))
    monkeypatch.setattr(Backend, "verify", lambda *a, **k: BackendResult("semantic", "ok", outcome="FAIL", complete=False))
    monkeypatch.setattr(Backend, "verify_cir", lambda *a, **k: BackendResult("semantic", "ok", outcome="FAIL", complete=False))
    cell = _run(tmp_path, monkeypatch, clock, "G0", [RUST], "schema")
    cell["compile_wall_ms"] = "12"
    assert any("compile_wall_ms" in error for error in validate_cell(cell))
    cell["compile_wall_ms"] = 12
    cell["history"] = [{"wall_ms": "12"}]
    assert any("history[0].wall_ms" in error for error in validate_cell(cell))
    cell["history"] = []
    cell["baseline"] = {
        "rounds": [{
            "call": 1, "stage": "generate", "reply_kind": "program", "version": 1,
            "compiled": True, "compile": "ok", "compile_wall_ms": "12",
            "feedback_sha256": None, "feedback_bytes": 0, "truncated": False,
            "tools": {"clippy": {"wall_ms": "12"}},
        }],
        "final_version": 1,
        "tools_missing": [],
    }
    errors = validate_cell(cell)
    assert any("rounds[0].compile_wall_ms" in error for error in errors)
    assert any("tools.clippy.wall_ms" in error for error in errors)
