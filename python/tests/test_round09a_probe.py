"""A8: the probe's nontrivial prompt distinguishes a silent gateway."""

import json
from types import SimpleNamespace

from skelnet import cli
from skelnet.models_probe import PROBE_NONTRIVIAL_USER
from skelnet.oracle import FakeOracle

from _fake_sdk import patch_build_client, write_env

SECRET = "PROBE-SECRET-KEY"


def _response(text, *, effort, tokens, summary=None, items=0):
    echo = None if effort is None else {"effort": effort}
    if summary:
        echo = dict(echo or {})
        echo["summary"] = summary
    usage = {"input_tokens": 4, "output_tokens": 9,
             "output_tokens_details": {"reasoning_tokens": tokens}}
    output = [{"type": "reasoning", "summary": summary}] if items else []
    return SimpleNamespace(
        output_text=text, status="completed", incomplete_details=None,
        usage=usage, model="gpt-6-luna", id="r", cost=None,
        reasoning=echo, output=output)


def _probe(tmp_path, monkeypatch, *, effort, tokens):
    def handler(kwargs):
        user = kwargs.get("input")
        requested = kwargs.get("reasoning") or {}
        if requested.get("summary") == "auto":
            return _response("YES", effort=effort, tokens=tokens, summary="because ABBA", items=1)
        if user == PROBE_NONTRIVIAL_USER:
            return _response("YES", effort=effort, tokens=tokens, items=1 if tokens else 0)
        return _response("OK", effort=effort, tokens=tokens)
    from _fake_sdk import FakeSDK
    sdk = FakeSDK(responses_handler=handler)
    patch_build_client(monkeypatch, sdk)
    env = write_env(tmp_path, OPENCODE_API_KEY=SECRET)
    out = tmp_path / "probe"
    rc = cli.main([
        "models", "probe", "--models", "GPT 6 Luna",
        "--out", str(out), "--env-file", str(env),
    ])
    assert rc == 0
    document = json.loads((out / "PROBE.json").read_text(encoding="utf-8"))
    assert SECRET not in (out / "PROBE.json").read_text(encoding="utf-8")
    record = document["models"][0]
    inputs = [call.get("input") for call in sdk.responses.calls]
    assert PROBE_NONTRIVIAL_USER in inputs
    assert any((call.get("reasoning") or {}).get("summary") == "auto"
               for call in sdk.responses.calls)
    return record, sdk


def test_diagnosis_model_reasons(tmp_path, monkeypatch):
    record, _sdk = _probe(tmp_path, monkeypatch, effort="medium", tokens=5)
    assert record["reasoning_diagnosis"] == "model_reasons"
    assert record["nontrivial_answer_ok"] is True
    assert record["reasoning_tokens_nontrivial"] == 5
    assert record["responses_reasoning_echo"]["effort"] == "medium"
    assert record["responses_reasoning_items"] == 1
    assert record["responses_output_tokens_details"] == {"reasoning_tokens": 5}
    assert record["responses_reasoning_summary_present"] is True
    assert record["reasoning_tokens_nontrivial_low"] == 5


def test_diagnosis_gateway_dropped(tmp_path, monkeypatch):
    record, _sdk = _probe(tmp_path, monkeypatch, effort=None, tokens=0)
    assert record["reasoning_diagnosis"] == "gateway_dropped_reasoning_param"
    assert record["responses_reasoning_echo"] is None
    assert record["reasoning_tokens_nontrivial"] == 0


def test_diagnosis_echo_without_tokens(tmp_path, monkeypatch):
    record, _sdk = _probe(tmp_path, monkeypatch, effort="medium", tokens=0)
    assert record["reasoning_diagnosis"] == "reasoning_not_reported_or_not_used"
    assert record["responses_reasoning_echo"]["effort"] == "medium"
    assert record["reasoning_tokens_nontrivial"] == 0


def test_summary_variant_is_probe_only(tmp_path, monkeypatch):
    def handler(kwargs):
        return _response("```rust\nfn main() { println!(\"DONE t1=1 t2=1\"); }\n```",
                         effort="medium", tokens=1)
    from _fake_sdk import FakeSDK
    sdk = FakeSDK(responses_handler=handler)
    patch_build_client(monkeypatch, sdk)
    env = write_env(tmp_path, OPENCODE_API_KEY=SECRET)
    out = tmp_path / "run"
    rc = cli.cmd_run(cli.build_parser().parse_args([
        "run", "--arm", "G0", "--model", "GPT 6 Luna",
        "--tasks", "lock-order/abba_2lock", "--reps", "1",
        "--out", str(out), "--env-file", str(env),
        "--budget-file", str(tmp_path / "budget.json"),
    ]), oracle_factory=lambda _t, _term: FakeOracle(True))
    assert rc == 0
    assert sdk.responses.calls
    assert all("summary" not in (call.get("reasoning") or {}) for call in sdk.responses.calls)
