"""R9d-P4: Qwen and Kimi default to streaming; DeepSeek and GPT unchanged.

Driven through the real `cli.main` run entry (only the outer SDK and the oracle
construction are replaced), so the captured kwargs are the ones the clients
actually send.
"""

import json
from pathlib import Path

import pytest

from skelnet import cli

from _fake_sdk import (FakeSDK, RUST, chat_response, patch_build_client,
                       responses_response, sequence_handler, write_env)

GOLDEN = json.loads(
    (Path(__file__).parent / "fixtures" / "round09c" / "golden_kwargs.json"
     ).read_text(encoding="utf-8"))

ENV_KEYS = {"Qwen": "DASHSCOPE_API_KEY", "Kimi": "MOONSHOT_API_KEY",
            "DeepSeek Flash": "DEEPSEEK_API_KEY", "GPT 6 Luna": "OPENCODE_API_KEY"}


def _fake_oracle_factory(**kwargs):
    from skelnet.oracle import FakeOracle
    return lambda task_dir, terminal: FakeOracle(True)


def _capture(tmp_path, monkeypatch, model):
    monkeypatch.setenv(ENV_KEYS[model], "SECRET")
    monkeypatch.setattr(cli, "default_oracle_factory", _fake_oracle_factory)
    sdk = FakeSDK(chat_handler=sequence_handler([chat_response(RUST)]),
                  responses_handler=sequence_handler([responses_response(RUST)]))
    patch_build_client(monkeypatch, sdk)
    env = write_env(tmp_path, **{ENV_KEYS[model]: "SECRET"})
    out = tmp_path / model.replace(" ", "_")

    rc = cli.main(["run", "--arm", "G0", "--model", model,
                   "--tasks", "lock-order/abba_2lock", "--reps", "1",
                   "--rounds", "1", "--out", str(out), "--env-file", str(env),
                   "--budget-file", str(tmp_path / "budget.json")])
    assert rc == 0
    calls = sdk.responses.calls or sdk.chat.completions.calls
    call = dict(calls[0])
    for key in ("messages", "input", "instructions", "extra_headers"):
        call.pop(key, None)
    return call


@pytest.mark.parametrize("model", ["Qwen", "Kimi"])
def test_streaming_channels_send_stream(tmp_path, monkeypatch, model):
    call = _capture(tmp_path, monkeypatch, model)
    assert call["stream"] is True
    assert call["stream_options"] == {"include_usage": True}


@pytest.mark.parametrize("model", ["DeepSeek Flash", "GPT 6 Luna"])
def test_unchanged_models_match_main(tmp_path, monkeypatch, model):
    assert _capture(tmp_path, monkeypatch, model) == GOLDEN[model]
