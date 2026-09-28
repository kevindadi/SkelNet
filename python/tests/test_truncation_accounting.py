"""M3/M4: truncation retry accounting and billable token totals."""

import json

from skelnet import cli
from skelnet.oracle import FakeOracle

from _fake_sdk import (FakeSDK, chat_response, patch_build_client,
                       responses_response, run_args, sequence_handler,
                       write_env)

USAGE = {"prompt_tokens": 10, "completion_tokens": 5,
         "completion_tokens_details": {"reasoning_tokens": 3}}
RUST = "```rust\nfn main() {}\n```"

MODELS = {
    "GPT 6 Luna": ("OPENCODE_API_KEY", "responses"),
    "Kimi": ("OPENCODE_API_KEY", "chat"),
    "DeepSeek Flash": ("DEEPSEEK_API_KEY", "chat"),
    "Qwen": ("DASHSCOPE_API_KEY", "chat"),
}


def _run(tmp_path, monkeypatch, model, sdk, name=None):
    key_env, _surface = MODELS[model]
    patch_build_client(monkeypatch, sdk)
    env = write_env(tmp_path, **{key_env: "k"})
    out = tmp_path / (name or model.replace(" ", "_"))
    args = run_args("G0", out, model=model, env_file=str(env),
                    budget_file=str(tmp_path / "budget.json"))
    rc = cli.cmd_run(args, oracle_factory=lambda t, term: FakeOracle(True))
    return out, rc


def _cell(out, model):
    return json.loads(
        (out / "cells" / "lock-order" / "abba_2lock" / "0" / "result.json").read_text())


def test_truncation_retry_for_all_four_models(tmp_path, monkeypatch):
    for model, (_env, surface) in MODELS.items():
        if surface == "responses":
            sdk = FakeSDK(responses_handler=sequence_handler([
                responses_response("", status="incomplete",
                                   incomplete_reason="max_output_tokens", usage=USAGE),
                responses_response(RUST, usage=USAGE),
            ]))
            calls = None
        else:
            sdk = FakeSDK(chat_handler=sequence_handler([
                chat_response("", finish_reason="length", usage=USAGE),
                chat_response(RUST, finish_reason="stop", usage=USAGE),
            ]))
            calls = None
        out, rc = _run(tmp_path, monkeypatch, model, sdk)
        assert rc == 0, model
        cell = _cell(out, model)
        call = cell["calls"][0]
        assert call["truncation_retry"] is True, model
        assert len(call["finish_reasons"]) == 2, model
        assert cell["budget_used"]["calls"] == 1, model
        assert cell["budget_used"]["tokens"] == 30, model  # (10+5) * 2
        if surface == "responses":
            assert sdk.responses.calls[1]["max_output_tokens"] == 65536, model
        else:
            assert sdk.chat.completions.calls[1]["max_tokens"] == 65536, model
        log = (out / "evidence" / "requests.jsonl").read_text().splitlines()
        assert len(log) == 2, model


def test_direct_twice_truncated(tmp_path, monkeypatch):
    sdk = FakeSDK(chat_handler=sequence_handler([
        chat_response("", finish_reason="length", usage=USAGE),
        chat_response("", finish_reason="length", usage=USAGE),
    ]))
    out, rc = _run(tmp_path, monkeypatch, "DeepSeek Flash", sdk)
    assert rc == 0
    assert _cell(out, "DeepSeek Flash")["error"] == "transport_truncated"


def test_responses_twice_truncated(tmp_path, monkeypatch):
    sdk = FakeSDK(responses_handler=sequence_handler([
        responses_response("", status="incomplete",
                           incomplete_reason="max_output_tokens", usage=USAGE),
        responses_response("", status="incomplete",
                           incomplete_reason="max_output_tokens", usage=USAGE),
    ]))
    out, rc = _run(tmp_path, monkeypatch, "GPT 6 Luna", sdk)
    assert rc == 0
    assert _cell(out, "GPT 6 Luna")["error"] == "transport_truncated"


def _error_event(out):
    events = [json.loads(line) for line in
              (out / "audit.jsonl").read_text().splitlines() if line.strip()]
    errors = [event for event in events if event.get("status") == "error"]
    assert len(errors) == 1
    return errors[0]


def _assert_twice_truncated_accounted(out, model):
    cell = _cell(out, model)
    assert cell["error"] == "transport_truncated"
    call = cell["calls"][0]
    assert call["truncation_retry"] is True
    assert len(call["finish_reasons"]) == 2
    # Two attempts of input 10 / output 5 / reasoning 3 each.
    assert call["usage"]["input"] == 20
    assert call["usage"]["output"] == 10
    assert call["usage"]["reasoning"] == 6
    assert cell["budget_used"]["calls"] == 1
    assert cell["budget_used"]["tokens"] == 30  # billable = input + output
    event = _error_event(out)
    assert event["truncation_retry"] is True
    assert len(event["finish_reasons"]) == 2


def test_twice_truncated_keeps_usage_direct(tmp_path, monkeypatch):
    sdk = FakeSDK(chat_handler=sequence_handler([
        chat_response("", finish_reason="length", usage=USAGE),
        chat_response("", finish_reason="length", usage=USAGE),
    ]))
    out, rc = _run(tmp_path, monkeypatch, "DeepSeek Flash", sdk)
    assert rc == 0
    _assert_twice_truncated_accounted(out, "DeepSeek Flash")


def test_twice_truncated_keeps_usage_responses(tmp_path, monkeypatch):
    sdk = FakeSDK(responses_handler=sequence_handler([
        responses_response("", status="incomplete",
                           incomplete_reason="max_output_tokens", usage=USAGE),
        responses_response("", status="incomplete",
                           incomplete_reason="max_output_tokens", usage=USAGE),
    ]))
    out, rc = _run(tmp_path, monkeypatch, "GPT 6 Luna", sdk)
    assert rc == 0
    _assert_twice_truncated_accounted(out, "GPT 6 Luna")
