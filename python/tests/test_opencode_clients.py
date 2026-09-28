"""A2/A3/A4/A5/A6/A7/A11/A12: client request building, retries, truncation,
sessions, Responses mapping and DashScope streaming."""

import pytest

from skelnet import channels
from skelnet.direct import DirectChatClient
from skelnet.opencode_go import OpenCodeGoClient, OpenCodeGoResponsesClient
from skelnet.params import RunParams, params_for_model, seed_for
from skelnet.transport import (TemperatureRejected, TransportTruncated,
                               build_registry, resolve_model)

from _fake_sdk import (APIConnectionError, FakeSDK, chat_response,
                       responses_response)


class _Budget:
    def __init__(self):
        self.calls = 0

    def reserve(self):
        self.calls += 1


def _params(**over):
    base = {"thinking": True, "reasoning_effort": None, "supports_seed": False}
    base.update(over)
    return RunParams(**base)


def _spec(name):
    return resolve_model(build_registry(), name)


# ── A2: request parameters ───────────────────────────────────────────
def test_provider_default_omits_temperature(tmp_path):
    sdk = FakeSDK(chat_handler=lambda k: chat_response("OK"))
    client = DirectChatClient(api_key="x", base_url="http://x", model="m",
                              budget=_Budget(), evidence_dir=tmp_path,
                              params=_params(), sdk_client=sdk)
    client.complete("sys", "user")
    assert "temperature" not in sdk.chat.completions.calls[0]


def test_fixed_temperature_is_sent(tmp_path):
    sdk = FakeSDK(chat_handler=lambda k: chat_response("OK"))
    client = DirectChatClient(api_key="x", base_url="http://x", model="m",
                              budget=_Budget(), evidence_dir=tmp_path,
                              params=_params(temperature_policy="fixed", temperature=0.5),
                              sdk_client=sdk)
    client.complete("sys", "user")
    assert sdk.chat.completions.calls[0]["temperature"] == 0.5


def test_build_client_thinking_switches(tmp_path):
    ds = _spec("DeepSeek Flash")
    sdk = FakeSDK(chat_handler=lambda k: chat_response("OK"))
    client = channels.build_client(ds, params_for_model(ds), budget=_Budget(),
                                   evidence_dir=tmp_path, api_key="x", sdk_client=sdk)
    client.complete("s", "u")
    assert sdk.chat.completions.calls[0]["extra_body"] == {"thinking": {"type": "enabled"}}

    qw = _spec("Qwen")
    sdk2 = FakeSDK(chat_handler=lambda k: chat_response("OK"))
    client2 = channels.build_client(qw, params_for_model(qw), budget=_Budget(),
                                    evidence_dir=tmp_path, api_key="x", sdk_client=sdk2)
    client2.complete("s", "u")
    assert sdk2.chat.completions.calls[0]["extra_body"] == {"enable_thinking": True}


def test_kimi_reasoning_effort_and_gpt_reasoning(tmp_path):
    # Kimi is on the Moonshot direct channel (R2d): top-level reasoning_effort
    # "high", no thinking key, no temperature.
    kimi = _spec("Kimi")
    sdk = FakeSDK(chat_handler=lambda k: chat_response("OK"))
    client = channels.build_client(kimi, params_for_model(kimi), budget=_Budget(),
                                   evidence_dir=tmp_path, api_key="x", sdk_client=sdk)
    client.complete("s", "u")
    call = sdk.chat.completions.calls[0]
    assert call["reasoning_effort"] == "high"
    assert "thinking" not in call
    assert "temperature" not in call

    gpt = _spec("GPT 6 Luna")
    sdk2 = FakeSDK(responses_handler=lambda k: responses_response("OK"))
    client2 = OpenCodeGoResponsesClient(api_key="x", base_url="http://x",
                                        model=gpt.model_id, budget=_Budget(),
                                        evidence_dir=tmp_path,
                                        params=params_for_model(gpt), sdk_client=sdk2)
    client2.complete("s", "u")
    call = sdk2.responses.calls[0]
    assert call["reasoning"] == {"effort": "medium"}
    assert call["max_output_tokens"] == gpt.max_output_tokens
    assert "temperature" not in call


def test_seed_rules(tmp_path):
    # DeepSeek supports per-cell seeds.
    ds = _spec("DeepSeek Flash")
    sdk = FakeSDK(chat_handler=lambda k: chat_response("OK"))
    client = channels.build_client(ds, params_for_model(ds), budget=_Budget(),
                                   evidence_dir=tmp_path, api_key="x", sdk_client=sdk)
    client.set_cell("task", 0)
    client.complete("s", "u")
    assert sdk.chat.completions.calls[0]["seed"] == seed_for("task", 0)

    # Kimi (Moonshot) has no documented seed parameter: none is sent.
    kimi = _spec("Kimi")
    sdk_kimi = FakeSDK(chat_handler=lambda k: chat_response("OK"))
    client_kimi = channels.build_client(kimi, params_for_model(kimi), budget=_Budget(),
                                        evidence_dir=tmp_path, api_key="x",
                                        sdk_client=sdk_kimi)
    client_kimi.set_cell("task", 0)
    client_kimi.complete("s", "u")
    assert "seed" not in sdk_kimi.chat.completions.calls[0]

    # Responses never send a seed.
    gpt = _spec("GPT 6 Luna")
    sdk2 = FakeSDK(responses_handler=lambda k: responses_response("OK"))
    client2 = OpenCodeGoResponsesClient(api_key="x", base_url="http://x",
                                        model=gpt.model_id, budget=_Budget(),
                                        evidence_dir=tmp_path,
                                        params=params_for_model(gpt), sdk_client=sdk2)
    client2.set_cell("task", 0)
    client2.complete("s", "u")
    assert "seed" not in sdk2.responses.calls[0]


# ── A3: no silent temperature fallback ───────────────────────────────
def test_temperature_rejected_once(tmp_path):
    def handler(k):
        raise Exception("temperature is not supported")
    sdk = FakeSDK(chat_handler=handler)
    client = OpenCodeGoClient(api_key="x", base_url="http://x", model="m",
                              budget=_Budget(), evidence_dir=tmp_path,
                              params=_params(temperature_policy="fixed", temperature=1.0),
                              sdk_client=sdk)
    with pytest.raises(TemperatureRejected):
        client.complete("s", "u")
    assert len(sdk.chat.completions.calls) == 1


# ── A4: shared retry wrapper ─────────────────────────────────────────
def test_transport_retry_attempts(tmp_path):
    state = {"n": 0}

    def handler(k):
        state["n"] += 1
        if state["n"] <= 2:
            raise APIConnectionError("boom")
        return chat_response("OK")
    sdk = FakeSDK(chat_handler=handler)
    client = OpenCodeGoClient(api_key="x", base_url="http://x", model="m",
                              budget=_Budget(), evidence_dir=tmp_path,
                              params=_params(), sdk_client=sdk,
                              sleep=lambda _s: None)
    outcome = client.complete("s", "u")
    assert outcome.transport_attempt == 3
    assert len(sdk.chat.completions.calls) == 3


def test_non_retryable_exception_once(tmp_path):
    def handler(k):
        raise ValueError("nope")
    sdk = FakeSDK(chat_handler=handler)
    client = OpenCodeGoClient(api_key="x", base_url="http://x", model="m",
                              budget=_Budget(), evidence_dir=tmp_path,
                              params=_params(), sdk_client=sdk,
                              sleep=lambda _s: None)
    with pytest.raises(ValueError):
        client.complete("s", "u")
    assert len(sdk.chat.completions.calls) == 1


# ── A6: truncation retry ─────────────────────────────────────────────
def test_truncation_retries_with_larger_cap(tmp_path):
    state = {"n": 0}

    def handler(k):
        state["n"] += 1
        if state["n"] == 1:
            return chat_response("", finish_reason="length")
        return chat_response("OK")
    sdk = FakeSDK(chat_handler=handler)
    params = _params(max_output_tokens=1000, max_output_tokens_cap=65536)
    client = OpenCodeGoClient(api_key="x", base_url="http://x", model="m",
                              budget=_Budget(), evidence_dir=tmp_path,
                              params=params, sdk_client=sdk)
    outcome = client.complete("s", "u")
    assert outcome.text == "OK"
    assert len(sdk.chat.completions.calls) == 2
    assert sdk.chat.completions.calls[0]["max_tokens"] == 1000
    assert sdk.chat.completions.calls[1]["max_tokens"] == 2000


def test_truncation_twice_is_transport_truncated(tmp_path):
    sdk = FakeSDK(chat_handler=lambda k: chat_response("", finish_reason="length"))
    client = OpenCodeGoClient(api_key="x", base_url="http://x", model="m",
                              budget=_Budget(), evidence_dir=tmp_path,
                              params=_params(max_output_tokens=100,
                                             max_output_tokens_cap=200),
                              sdk_client=sdk)
    with pytest.raises(TransportTruncated):
        client.complete("s", "u")
    assert len(sdk.chat.completions.calls) == 2


# ── A5: Responses finish_reason + cost ───────────────────────────────
def test_responses_finish_reason_mapping(tmp_path):
    sdk = FakeSDK(responses_handler=lambda k: responses_response(
        "hi", status="completed", cost=0.25))
    client = OpenCodeGoResponsesClient(api_key="x", base_url="http://x", model="m",
                                       budget=_Budget(), evidence_dir=tmp_path,
                                       params=_params(), sdk_client=sdk)
    outcome = client.complete("s", "u")
    assert outcome.finish_reason == "stop"
    assert outcome.cost == 0.25

    sdk2 = FakeSDK(responses_handler=lambda k: responses_response(
        "", status="incomplete", incomplete_reason="max_output_tokens"))
    client2 = OpenCodeGoResponsesClient(api_key="x", base_url="http://x", model="m",
                                        budget=_Budget(), evidence_dir=tmp_path,
                                        params=_params(max_output_tokens=10,
                                                       max_output_tokens_cap=10),
                                        sdk_client=sdk2)
    with pytest.raises(TransportTruncated):
        client2.complete("s", "u")
    assert sdk2.responses.calls[0]  # finish_reason mapped to length internally


# ── A7: fresh session per cell ───────────────────────────────────────
def test_cmd_run_gets_a_new_session_per_cell(tmp_path):
    from skelnet import cli
    from skelnet.oracle import FakeOracle
    from _fake_sdk import run_args

    sdk = FakeSDK(chat_handler=lambda k: chat_response(
        "```rust\nfn main() {}\n```"))
    kimi = _spec("Kimi")

    def factory(spec, out):
        return OpenCodeGoClient(api_key="x", base_url="http://x", model=kimi.model_id,
                                budget=_Budget(), evidence_dir=out / "evidence",
                                params=params_for_model(spec), sdk_client=sdk)

    out = tmp_path / "run"
    args = run_args("G0", out, model="Kimi", reps=2)
    cli.cmd_run(args, client_factory=factory,
                oracle_factory=lambda t, term: FakeOracle(True))
    sessions = [c["extra_headers"]["x-opencode-session"]
                for c in sdk.chat.completions.calls]
    assert len(sessions) == 2
    assert sessions[0] != sessions[1]


def test_session_per_cell(tmp_path):
    sdk = FakeSDK(chat_handler=lambda k: chat_response("OK"))
    client = OpenCodeGoClient(api_key="x", base_url="http://x", model="m",
                              budget=_Budget(), evidence_dir=tmp_path,
                              params=_params(), sdk_client=sdk)
    client.complete("s", "u")
    first = sdk.chat.completions.calls[-1]["extra_headers"]["x-opencode-session"]
    client.complete("s", "u")
    same = sdk.chat.completions.calls[-1]["extra_headers"]["x-opencode-session"]
    assert first == same
    client.new_session()
    client.complete("s", "u")
    changed = sdk.chat.completions.calls[-1]["extra_headers"]["x-opencode-session"]
    assert changed != first


# ── A12: DashScope streaming ─────────────────────────────────────────
def test_dashscope_streaming(tmp_path):
    def handler(k):
        assert k["stream"] is True
        assert k["stream_options"] == {"include_usage": True}
        return iter([
            _chunk("Hel", reasoning="think", finish=None),
            _chunk("lo", reasoning=" more", finish="stop", usage={"prompt_tokens": 2,
                                                                  "completion_tokens": 3}),
        ])
    sdk = FakeSDK(chat_handler=handler)
    params = _params(stream=True)
    client = DirectChatClient(api_key="x", base_url="http://x", model="m",
                              budget=_Budget(), evidence_dir=tmp_path,
                              params=params, sdk_client=sdk)
    outcome = client.complete("s", "u")
    assert outcome.text == "Hello"
    assert outcome.reasoning_content == "think more"
    assert outcome.usage == {"prompt_tokens": 2, "completion_tokens": 3}
    assert outcome.finish_reason == "stop"


def _chunk(content, *, reasoning=None, finish=None, usage=None):
    from types import SimpleNamespace
    delta = SimpleNamespace(content=content, reasoning_content=reasoning)
    choice = SimpleNamespace(delta=delta, finish_reason=finish)
    return SimpleNamespace(choices=[choice], usage=usage, model="m", id="r1")
