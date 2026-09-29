"""A3: requests.jsonl stores a reasoning hash, not the reasoning text."""

import gzip
import hashlib
import json
import subprocess
from pathlib import Path

from skelnet import cli
from skelnet.cache import CachedClient
from skelnet.direct import DirectChatClient
from skelnet.oracle import FakeOracle
from skelnet.params import RunParams

from _fake_sdk import FakeSDK, chat_response, patch_build_client, write_env

REASON_A = "thinking-trace-alpha-UNIQUE"
REASON_B = "thinking-trace-beta-UNIQUE"


class _Budget:
    def reserve(self):
        return None

    def add_tokens(self, _tokens):
        return None


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _client(tmp_path, sdk, *, reasoning_log="hash"):
    return DirectChatClient(
        api_key="k", base_url="https://example.invalid", model="m",
        budget=_Budget(), evidence_dir=tmp_path / "evidence",
        params=RunParams(max_output_tokens=8), sdk_client=sdk,
        reasoning_log=reasoning_log, sleep=lambda _s: None)


def test_jsonl_has_hash_not_reasoning_text(tmp_path):
    sdk = FakeSDK(chat_handler=lambda kwargs: chat_response(
        "fn main() {}", reasoning=REASON_A))
    client = _client(tmp_path, sdk)
    outcome = client.complete("sys", "user")
    assert outcome.reasoning_content == REASON_A
    lines = (tmp_path / "evidence" / "requests.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert REASON_A not in lines[0]
    assert "reasoning_content" not in row
    assert row["reasoning_sha256"] == _sha(REASON_A)
    assert row["reasoning_chars"] == len(REASON_A)
    assert row["reasoning_bytes"] == len(REASON_A.encode("utf-8"))


def test_truncated_retry_and_gzip_written_once(tmp_path):
    calls = {"n": 0}

    def handler(_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return chat_response("", finish_reason="length", reasoning=REASON_B)
        return chat_response("fn main() {}", reasoning=REASON_B)

    client = _client(tmp_path, FakeSDK(chat_handler=handler), reasoning_log="gzip")
    outcome = client.complete("sys", "user")
    assert outcome.reasoning_content == REASON_B
    rows = [json.loads(line) for line in
            (tmp_path / "evidence" / "requests.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    blob = (tmp_path / "evidence" / "requests.jsonl").read_text(encoding="utf-8")
    assert REASON_B not in blob
    for row in rows:
        assert row["reasoning_sha256"] == _sha(REASON_B)
        assert row["reasoning_chars"] == len(REASON_B)
        assert row["reasoning_bytes"] == len(REASON_B.encode())
    path = tmp_path / "evidence" / "reasoning" / f"{_sha(REASON_B)}.txt.gz"
    assert gzip.decompress(path.read_bytes()).decode("utf-8") == REASON_B
    path.write_bytes(b"STALE")
    client.complete("sys", "user-again")
    assert path.read_bytes() == b"STALE"


def test_empty_reasoning_is_null(tmp_path):
    sdk = FakeSDK(chat_handler=lambda kwargs: chat_response("ok", reasoning=None))
    _client(tmp_path, sdk).complete("sys", "user")
    row = json.loads((tmp_path / "evidence" / "requests.jsonl").read_text().splitlines()[0])
    assert row["reasoning_sha256"] is None
    assert row["reasoning_chars"] is None
    assert row["reasoning_bytes"] is None


def test_cmd_run_gzip_and_replay_keep_reasoning(tmp_path, monkeypatch):
    secret = "REASONING-BODY-NOT-IN-JSONL"
    responses = [
        chat_response("short", finish_reason="length", reasoning=secret),
        chat_response("```rust\nfn main() { println!(\"DONE t1=1 t2=1\"); }\n```",
                      reasoning=secret),
    ]
    sdk = FakeSDK(chat_handler=lambda _kwargs: responses.pop(0))
    patch_build_client(monkeypatch, sdk)
    env_file = write_env(tmp_path, DEEPSEEK_API_KEY="secret-key-value")
    out = tmp_path / "run"
    args = cli.build_parser().parse_args([
        "run", "--arm", "G0", "--tasks", "lock-order/abba_2lock",
        "--reps", "1", "--rounds", "1", "--out", str(out),
        "--env-file", str(env_file), "--evidence-reasoning", "gzip",
        "--budget-file", str(tmp_path / "budget.json"),
    ])
    rc = cli.cmd_run(args, oracle_factory=lambda _t, _term: FakeOracle(True))
    assert rc == 0
    log = (out / "evidence" / "requests.jsonl").read_text(encoding="utf-8")
    assert secret not in log
    assert "secret-key-value" not in log
    row = json.loads(log.splitlines()[-1])
    gz = out / "evidence" / "reasoning" / f"{row['reasoning_sha256']}.txt.gz"
    assert gzip.decompress(gz.read_bytes()).decode("utf-8") == secret
    cached = list((out / "cache").glob("*.json"))
    assert cached
    assert any(json.loads(path.read_text())["reasoning_content"] == secret for path in cached)

    seen = []
    original = CachedClient.complete

    def spy(self, system, user):
        outcome = original(self, system, user)
        seen.append(getattr(outcome, "reasoning_content", None))
        return outcome

    monkeypatch.setattr(CachedClient, "complete", spy)
    replay_out = tmp_path / "replay"
    replay_args = cli.build_parser().parse_args([
        "run", "--arm", "G0", "--tasks", "lock-order/abba_2lock",
        "--reps", "1", "--rounds", "1", "--out", str(replay_out),
        "--replay-from", str(out), "--evidence-reasoning", "gzip",
        "--budget-file", str(tmp_path / "budget-replay.json"),
    ])
    rc = cli.cmd_run(replay_args, oracle_factory=lambda _t, _term: FakeOracle(True))
    assert rc == 0
    assert seen and seen[0] == secret


def test_gitignore_covers_raw_layer():
    root = Path(__file__).resolve().parents[2]
    for rel in ("experiments/x/evidence/requests.jsonl",
                "experiments/x/raw/a.txt",
                "experiments/x/audit.jsonl"):
        proc = subprocess.run(
            ["git", "check-ignore", "--no-index", rel],
            cwd=root, capture_output=True, text=True)
        if proc.returncode == 128:
            import pytest
            pytest.skip("not a git repository")
        assert proc.returncode == 0, rel
