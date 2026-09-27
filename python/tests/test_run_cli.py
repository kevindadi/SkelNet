"""T1/T5: prompt routing through the CLI, MANIFEST completeness, audit cell ids."""

import hashlib
import json
from pathlib import Path

import pytest

from skelnet import cli, prompts
from skelnet.backend import repo_root
from skelnet.oracle import FakeOracle

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


def _args(arm: str, out: Path, rounds: int = 2):
    parser = cli.build_parser()
    return parser.parse_args([
        "run", "--arm", arm, "--model", "DeepSeek Flash",
        "--tasks", "lock-order/abba_2lock", "--reps", "1",
        "--rounds", str(rounds), "--out", str(out)])


def _run_arm(arm: str, responses: list[str], tmp_path: Path):
    created: list[RecordingClient] = []

    def factory(spec, out):
        client = RecordingClient(responses)
        created.append(client)
        return client

    out = tmp_path / f"run_{arm}"
    args = _args(arm, out)
    rc = cli.cmd_run(args, client_factory=factory, oracle=FakeOracle(True))
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
