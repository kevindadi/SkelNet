"""A2: code-fence info strings are not part of the extracted program."""

import json
from types import SimpleNamespace

from skelnet import cli
from skelnet.oracle import FakeOracle
from skelnet.pipeline import classify_rust_reply, extract_cir, extract_rust, extract_skel

RUST_BODY = "fn main() {\n    println!(\"DONE t1=1 t2=1\");\n}"


def _fenced(info: str, body: str, *, close: bool = True) -> str:
    fence = f"```{info}\n{body}"
    return fence + ("\n```" if close else "")


def test_extract_strips_info_strings():
    assert extract_rust(_fenced(" Rust", RUST_BODY)) == RUST_BODY
    assert extract_rust(_fenced("rs", RUST_BODY)) == RUST_BODY
    assert extract_rust(_fenced("rust,ignore", RUST_BODY)) == RUST_BODY
    assert extract_rust(_fenced(' rust title="main.rs"', RUST_BODY)) == RUST_BODY
    assert extract_rust(_fenced("", RUST_BODY)) == RUST_BODY
    assert extract_rust(_fenced("rust", RUST_BODY, close=False)) == RUST_BODY
    mixed = _fenced("json", "{\"a\": 1}") + "\n" + _fenced("rust", RUST_BODY)
    assert extract_rust(mixed) == RUST_BODY
    assert extract_cir(mixed) == "{\"a\": 1}"
    assert extract_skel(_fenced(" skeleton", "skeleton t;")) == "skeleton t;"
    assert extract_cir(_fenced("JSON", "{\"ok\": true}")) == "{\"ok\": true}"
    assert "Rust" not in extract_rust(_fenced(" Rust", RUST_BODY)).splitlines()[0]


def test_classify_rules_are_unchanged():
    assert classify_rust_reply(_fenced(" Rust", RUST_BODY)).kind == "program"
    assert classify_rust_reply(_fenced("skel", "fn main() {}")).kind == "other"


def test_cmd_run_g0_drops_a_rust_info_string(tmp_path):
    """A ``` Rust fence must not be compiled as if the tag were source."""
    reply = _fenced(" Rust", RUST_BODY)

    class Client:
        def __init__(self):
            self.n = 0

        def complete(self, system, user):
            self.n += 1
            return SimpleNamespace(
                text=reply, usage=None, requested_model="deepseek-v4-flash",
                response_model=None, request_id="r",
                transport_attempt=1, cost=None, finish_reason="stop")

    class Runner:
        def __call__(self, cmd, cwd, timeout, env):
            from pathlib import Path
            main = Path(cwd) / "src" / "main.rs"
            source = main.read_text(encoding="utf-8") if main.is_file() else ""
            if "build" in [str(part) for part in cmd] and source.startswith("Rust"):
                payload = {"reason": "compiler-message", "message": {
                    "level": "error", "message": "expected item",
                    "code": {"code": "E0425"},
                    "rendered": "error[E0425]: expected item\n"}}
                return SimpleNamespace(returncode=101, stdout=json.dumps(payload),
                                       stderr="error[E0425]: expected item")
            return SimpleNamespace(returncode=0, stdout="DONE t1=1 t2=1\n", stderr="")

    holder = {}

    def factory(spec, out):
        holder["client"] = Client()
        return holder["client"]

    out = tmp_path / "run"
    args = cli.build_parser().parse_args([
        "run", "--arm", "G0", "--tasks", "lock-order/abba_2lock",
        "--reps", "1", "--rounds", "1", "--out", str(out),
        "--budget-file", str(tmp_path / "budget.json"),
    ])
    rc = cli.cmd_run(args, client_factory=factory, oracle_factory=lambda _t, _term: FakeOracle(True),
                     oracle_runner=Runner())
    assert rc == 0
    cell_dir = out / "cells" / "lock-order" / "abba_2lock" / "0"
    cell = json.loads((cell_dir / "result.json").read_text(encoding="utf-8"))
    candidate = (cell_dir / "candidate.rs").read_text(encoding="utf-8")
    assert cell["accepted"] is True
    assert not candidate.startswith("Rust")
    assert candidate.splitlines()[0] == "fn main() {"
    assert holder["client"].n == 1
