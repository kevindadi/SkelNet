"""T1/T5: prompt routing through the CLI, MANIFEST completeness, audit cell ids."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from skelnet import cli, prompts
from skelnet.backend import repo_root
from skelnet.oracle import FakeOracle, RustOracle

BUGGY = """```skel
skeleton abba_bug;
mutex a;
mutex b;
@R1
fn main() { scope { spawn t1(); spawn t2(); } }
@R2 @R4
fn t1() { lock a { lock b { } } }
@R3 @R4
fn t2() { lock b { lock a { } } }
```"""

FIXED = """```skel
skeleton abba_ok;
mutex a;
mutex b;
@R1
fn main() { scope { spawn t1(); spawn t2(); } }
@R2 @R4
fn t1() { lock a { lock b { } } }
@R3 @R4
fn t2() { lock a { lock b { } } }
```"""

RUST = "```rust\nfn main() { println!(\"DONE\"); }\n```"


class _FakeOutcome:
    def __init__(self, text: str) -> None:
        self.text = text
        self.usage = None
        self.requested_model = "deepseek-flash"
        self.response_model = None
        self.request_id = None
        self.transport_attempt = 1
        self.cost = None


class RecordingClient:
    """A fake transport client that records the system prompts it receives."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.system_prompts: list[str] = []
        self.calls: list[tuple[str, str]] = []
        self._cursor = 0

    def complete(self, system: str, user: str):
        self.system_prompts.append(system)
        self.calls.append((system, user))
        text = self.responses[self._cursor] if self._cursor < len(self.responses) else ""
        self._cursor += 1
        return _FakeOutcome(text)


def _args(arm: str, out: Path, rounds: int = 2, reps: int = 1):
    parser = cli.build_parser()
    return parser.parse_args([
        "run", "--arm", arm, "--model", "DeepSeek Flash",
        "--tasks", "lock-order/abba_2lock", "--reps", str(reps),
        "--rounds", str(rounds), "--out", str(out)])


def _run_arm(arm: str, responses: list[str], tmp_path: Path, *,
             rounds: int = 2, reps: int = 1):
    created: list[RecordingClient] = []

    def factory(spec, out):
        client = RecordingClient(responses)
        created.append(client)
        return client

    out = tmp_path / f"run_{arm}"
    args = _args(arm, out, rounds=rounds, reps=reps)
    rc = cli.cmd_run(args, client_factory=factory,
                     oracle_factory=lambda task_dir, terminal: FakeOracle(True))
    assert rc == 0
    return out, created[0]


def _joined_sha(assets) -> str:
    text = prompts.PROMPT_SEPARATOR.join(prompts.read_asset(a) for a in assets)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_skel_prompt_routing(tmp_path):
    out, client = _run_arm("SKEL", [BUGGY, FIXED, RUST], tmp_path)
    got = [hashlib.sha256(s.encode()).hexdigest() for s in client.system_prompts]
    assert got == [
        _joined_sha((prompts.SKEL_GENERATION_ASSET,)),
        _joined_sha((prompts.SKEL_GENERATION_ASSET, prompts.SKEL_FEEDBACK_ASSET)),
        _joined_sha((prompts.RUST_FROM_SKEL_ASSET,)),
    ]
    # The feedback-round system prompt still contains the generation grammar.
    feedback_prompt = client.system_prompts[1]
    assert prompts.read_asset(prompts.SKEL_GENERATION_ASSET) in feedback_prompt
    assert prompts.read_asset(prompts.SKEL_FEEDBACK_ASSET) in feedback_prompt


def test_cir_prompt_routing(tmp_path):
    root = repo_root()
    gold = (root / "benchmarks/tasks/lock-order/abba_2lock/gold.cir.json").read_text()
    out, client = _run_arm("CIR", ["not json", gold, RUST], tmp_path)
    got = [hashlib.sha256(s.encode()).hexdigest() for s in client.system_prompts]
    assert got == [
        _joined_sha((prompts.CIR_GENERATION_ASSET,)),
        _joined_sha((prompts.CIR_GENERATION_ASSET, prompts.CIR_FEEDBACK_ASSET)),
        _joined_sha((prompts.RUST_FROM_CIR_ASSET,)),
    ]
    feedback_prompt = client.system_prompts[1]
    assert prompts.read_asset(prompts.CIR_GENERATION_ASSET) in feedback_prompt
    assert prompts.read_asset(prompts.CIR_FEEDBACK_ASSET) in feedback_prompt


def test_g0_prompt_routing(tmp_path):
    out, client = _run_arm("G0", [RUST], tmp_path)
    got = [hashlib.sha256(s.encode()).hexdigest() for s in client.system_prompts]
    assert got == [_joined_sha((prompts.RUST_GENERATION_ASSET,))]


def test_budget_exact_upper_bound():
    assert cli._budget("G0", 1, 1, 4)["requests_per_task"] == 1
    assert cli._budget("SKEL", 1, 1, 4, "llm")["requests_per_task"] == 5
    assert cli._budget("SKEL", 1, 1, 4, "codegen")["requests_per_task"] == 4
    assert cli._budget("CIR", 2, 3, 4, "codegen")["requests"] == 2 * 3 * 4


def test_missing_route_raises():
    with pytest.raises(KeyError):
        prompts.system_prompt_for("SKEL", "nonexistent-stage")


def test_manifest_and_audit_cell_ids(tmp_path):
    out, client = _run_arm("SKEL", [BUGGY, FIXED, RUST], tmp_path)
    manifest = json.loads((out / "MANIFEST.json").read_text())
    for key in ("git_sha", "git_dirty", "binaries", "prompts", "model", "arm",
                "rounds", "reps", "seed", "temperature", "started_at", "ended_at"):
        assert key in manifest, key
    assert manifest["binaries"]["skelnet"]
    assert manifest["binaries"]["concir-backend"]
    assert manifest["arm"] == "SKEL"

    events = [json.loads(line) for line in
              (out / "audit.jsonl").read_text().splitlines() if line.strip()]
    assert events
    for event in events:
        assert event["task_id"] == "lock-order/abba_2lock"
        assert event["replicate"] == 0
        assert event["cell_id"] == "lock-order/abba_2lock/0"
    assert [e["stage"] for e in events] == ["generate", "feedback", "rust"]


def test_audit_rounds_and_cells(tmp_path):
    # Two reps, SKEL: bad -> bad -> good -> Rust (rounds=3).
    responses = [BUGGY, BUGGY, FIXED, RUST] * 2
    out, _ = _run_arm("SKEL", responses, tmp_path, rounds=3, reps=2)
    events = [json.loads(line) for line in
              (out / "audit.jsonl").read_text().splitlines() if line.strip()]
    by_cell: dict[str, list[dict]] = {}
    for event in events:
        by_cell.setdefault(event["cell_id"], []).append(event)
    assert len(by_cell) == 2, by_cell.keys()  # two distinct reps
    for cell_events in by_cell.values():
        seq = [(e["stage"], e["candidate_round"]) for e in cell_events]
        assert seq == [("generate", 1), ("feedback", 2), ("feedback", 3),
                       ("rust", 4)]
        attempt_ids = [e["attempt_id"] for e in cell_events]
        assert len(attempt_ids) == len(set(attempt_ids))
        # F1 metadata is recorded on every call.
        for event in cell_events:
            assert event["system_prompt_assets"]
            assert event["system_sha256"]
        assert len(cell_events[1]["system_prompt_assets"]) == 2


def test_terminal_wired_through_cmd_run(tmp_path):
    seen: dict[str, str | None] = {}

    def factory(task_dir, terminal):
        seen[Path(task_dir).name] = terminal
        return FakeOracle(True)

    out = tmp_path / "run_term"
    args = cli.build_parser().parse_args([
        "run", "--arm", "G0", "--tasks", "*", "--reps", "1", "--rounds", "1",
        "--out", str(out)])
    rc = cli.cmd_run(args, client_factory=lambda spec, o: RecordingClient([]),
                     oracle_factory=factory)
    assert rc == 0
    assert seen["abba_2lock"] == "DONE t1=1 t2=1"
    assert seen["rwlock_unsupported"] is None


def test_real_oracle_terminal_pass_through_cmd_run(tmp_path):
    def runner(cmd, cwd, timeout):
        if "build" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="DONE t1=1 t2=1\n", stderr="")

    out = tmp_path / "run_pass"
    args = cli.build_parser().parse_args([
        "run", "--arm", "G0", "--tasks", "lock-order/abba_2lock", "--reps", "1",
        "--rounds", "1", "--out", str(out)])
    rc = cli.cmd_run(
        args, client_factory=lambda spec, o: RecordingClient([RUST]),
        oracle_factory=lambda task_dir, terminal: RustOracle(
            terminal=terminal, runner=runner))
    assert rc == 0
    result = json.loads(
        (out / "cells" / "lock-order" / "abba_2lock" / "0" / "result.json").read_text())
    assert result["oracle"]["terminal_check"] == "pass"
    assert result["oracle"]["functional_ok"] is True


def test_report_columns(tmp_path):
    out, _ = _run_arm("SKEL", [BUGGY, FIXED, RUST], tmp_path)
    summary = json.loads((out / "SUMMARY.json").read_text())
    table = cli._report_markdown([summary])
    header = table.splitlines()[2]
    for column in ("parse rate", "check pass", "verify pass", "mean rounds",
                   "evidence", "functional"):
        assert column in header
    row = next(line for line in table.splitlines() if line.startswith("| run_"))
    # The first column is the run id, not a duplicate of the arm.
    assert row.startswith(f"| {summary['run_id']} |")
    assert "| SKEL |" in row


def test_report_g0_has_na_columns(tmp_path):
    out, _ = _run_arm("G0", [RUST], tmp_path)
    summary = json.loads((out / "SUMMARY.json").read_text())
    table = cli._report_markdown([summary])
    row = next(line for line in table.splitlines() if line.startswith("| run_"))
    cols = [c.strip() for c in row.strip().strip("|").split("|")]
    # run, arm, model, cells, parse, check, verify, mean, evidence, run ok, functional
    assert cols[6] == "-"  # verify pass (no verification stage in G0)
    assert cols[7] == "-"  # mean rounds
    assert cols[8] == "-"  # evidence
