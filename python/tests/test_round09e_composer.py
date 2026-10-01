"""Round 9e: Kimi is replaced by Cursor Composer 2.5.

Offline: the Cursor SDK is the only thing replaced (``sdk_client``); the real
``channels.build_client`` and ``CursorAgentClient`` still run.
"""

import json
from pathlib import Path
from types import SimpleNamespace

from skelnet import channels, cli
from skelnet.cursor import CursorAgentClient
from skelnet.oracle import FakeOracle
from skelnet.params import params_for_model
from skelnet.transport import (EXPERIMENTAL_MODEL_IDS, build_registry,
                               resolve_model)

from _fake_sdk import patch_build_client, run_args, write_env

SECRET = "SECRET-CURSOR-9E"
CELL = ("cells", "lock-order", "abba_2lock", "0")


class _Budget:
    def __init__(self):
        self.reserves = 0
        self.tokens = []

    def reserve(self):
        self.reserves += 1

    def add_tokens(self, tokens):
        self.tokens.append(tokens)


class _Result:
    def __init__(self, text, usage=None, status="finished"):
        self.result = text
        self.status = status
        self.usage = usage
        self.id = "run-1"


class _Run:
    def __init__(self, result):
        self._result = result

    def wait(self):
        return self._result


class _Agent:
    def __init__(self, result):
        self._result = result
        self.sent = []
        self.closed = False

    def send(self, message):
        self.sent.append(message)
        return _Run(self._result)

    def close(self):
        self.closed = True


class FakeCursor:
    """Minimal stand-in for ``cursor_sdk.Client``."""

    def __init__(self, result):
        self.result = result
        self.created = []
        self.agents = []

    def create_agent(self, options=None, **kwargs):
        agent = _Agent(self.result)
        self.created.append((options, kwargs))
        self.agents.append(agent)
        return agent


def _usage(input_tokens=10, output_tokens=5, reasoning=3, cached=1):
    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                           reasoning_tokens=reasoning, cache_read_tokens=cached,
                           cache_write_tokens=0)


# ── registry ─────────────────────────────────────────────────────────
def test_experimental_set_has_composer_not_kimi():
    ids = set(EXPERIMENTAL_MODEL_IDS)
    assert "composer-2.5" in ids
    assert "kimi-k2.7-code" not in ids
    registry = build_registry()
    composer = resolve_model(registry, "Composer 2.5")
    assert composer.status == "available"
    assert composer.channel == "cursor" and composer.model_id == "composer-2.5"
    kimi = resolve_model(registry, "Kimi")
    assert kimi.status == "available" and kimi.channel == "moonshot-direct"


# ── client unit ──────────────────────────────────────────────────────
def test_cursor_client_maps_text_and_usage(tmp_path):
    fake = FakeCursor(_Result("```rust\nfn main() {}\n```", usage=_usage()))
    budget = _Budget()
    spec = resolve_model(build_registry(), "Composer 2.5")
    client = CursorAgentClient(api_key="k", model="composer-2.5", budget=budget,
                               evidence_dir=tmp_path, params=params_for_model(spec),
                               sdk_client=fake)
    client.set_cell("lock-order/abba_2lock", 0)
    outcome = client.complete("SYS", "USER")
    assert "fn main" in outcome.text
    assert outcome.finish_reason == "stop"
    assert outcome.usage["input_tokens"] == 10 and outcome.usage["output_tokens"] == 5
    assert outcome.usage["reasoning_tokens"] == 3 and outcome.usage["cached_tokens"] == 1
    assert budget.reserves == 1 and budget.tokens
    assert budget.tokens[0] == {"input": 10, "output": 5, "reasoning": 3, "cached": 1}
    # The agent was created with the frozen model and an isolated cwd.
    options, kwargs = fake.created[0]
    assert kwargs["model"] == "composer-2.5"
    assert options.get("mode") == "plan"
    log = (tmp_path / "requests.jsonl").read_text().splitlines()
    assert json.loads(log[0])["content"].startswith("```rust")


def test_new_session_starts_a_fresh_agent(tmp_path):
    fake = FakeCursor(_Result("ok"))
    client = CursorAgentClient(api_key="k", model="composer-2.5", budget=_Budget(),
                               evidence_dir=tmp_path,
                               params=params_for_model(resolve_model(
                                   build_registry(), "Composer 2.5")),
                               sdk_client=fake)
    client.set_cell("t", 0)
    client.complete("S", "U")
    client.new_session()
    client.complete("S", "U")
    assert len(fake.agents) == 2
    assert fake.agents[0].closed is True


def test_cursor_client_error_run_status(tmp_path):
    fake = FakeCursor(_Result("", status="error"))
    client = CursorAgentClient(api_key="k", model="composer-2.5", budget=_Budget(),
                               evidence_dir=tmp_path,
                               params=params_for_model(resolve_model(
                                   build_registry(), "Composer 2.5")),
                               sdk_client=fake)
    try:
        client.complete("S", "U")
    except RuntimeError as exc:
        assert "status" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError")


# ── real path through cmd_run ────────────────────────────────────────
def test_composer_real_path_cmd_run(tmp_path, monkeypatch):
    fake = FakeCursor(_Result("```rust\nfn main() { println!(\"DONE\"); }\n```",
                              usage=_usage()))
    patch_build_client(monkeypatch, fake)
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    env = write_env(tmp_path, CURSOR_API_KEY=SECRET)
    out = tmp_path / "run"
    args = run_args("G0", out, model="Composer 2.5", reps=1,
                    env_file=str(env), budget_file=str(tmp_path / "budget.json"))
    rc = cli.cmd_run(args, oracle_factory=lambda t, term: FakeOracle(True))
    assert rc == 0
    result = json.loads(out.joinpath(*CELL, "result.json").read_text())
    assert result["model"] == "Composer 2.5"
    assert result["model_id"] == "composer-2.5"
    assert result["calls"][0]["stage"] == "generate"
    # The key value never reaches an artifact.
    for path in out.rglob("*"):
        if path.is_file():
            assert SECRET not in path.read_text(errors="ignore"), path
