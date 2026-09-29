"""R2d: Kimi runs on Moonshot direct, independently of the OpenCode gateway.

The whole suite is offline: the outer SDK is the only thing replaced, so
``cmd_run`` -> ``_build_provider`` -> ``channels.build_client`` -> the real
``DirectChatClient`` still runs.
"""

import json

import pytest

from skelnet import channels, cli, models_probe
from skelnet.channels import ChannelUnavailable
from skelnet.oracle import FakeOracle
from skelnet.params import params_for_model
from skelnet.transport import CHANNELS, build_registry, resolve_model

from _fake_sdk import (FakeSDK, RUST, chat_response, patch_build_client,
                       run_args, sequence_handler, sequence_responses_handler,
                       write_env)

SECRET = "SECRET-KIMI"

MOONSHOT_BASE_URL = "https://api.moonshot.cn/v1"
OPENCODE_BASE_URL = "https://opencode.ai/zen/go/v1"
CELL = ("cells", "lock-order", "abba_2lock", "0")


def _usage(reasoning=3):
    return {"prompt_tokens": 10, "completion_tokens": 5 + reasoning,
            "completion_tokens_details": {"reasoning_tokens": reasoning}}


def _capture_build(monkeypatch, sdk):
    """Keep the real ``channels.build_client``; inject only the outer SDK.

    Also captures the constructed client's ``base_url`` and the resolved
    ``api_key`` so the real channel wiring can be asserted.
    """
    original = channels.build_client
    captured: dict = {}

    def patched(spec, params, **kwargs):
        kwargs["sdk_client"] = sdk
        kwargs["sleep"] = lambda _seconds: None
        client = original(spec, params, **kwargs)
        captured["spec"] = spec
        captured["base_url"] = getattr(client, "base_url", None)
        captured["api_key"] = kwargs.get("api_key")
        captured["client"] = client
        return client

    monkeypatch.setattr(channels, "build_client", patched)
    return captured


def _clear_key_env(monkeypatch):
    """Register the API-key vars for teardown, then remove them.

    ``delenv`` alone does not register a variable that was already absent, so
    set it first to guarantee ``monkeypatch`` restores the developer's real
    environment (``load_dotenv(override=True)`` writes straight to
    ``os.environ`` and would otherwise leak ``MOONSHOT_API_KEY=SECRET-KIMI``).
    """
    for key in ("OPENCODE_API_KEY", "MOONSHOT_API_KEY"):
        monkeypatch.setenv(key, "x")
        monkeypatch.delenv(key)


def _run(tmp_path, monkeypatch, sdk, *, model="Kimi", env=None, name="run"):
    _clear_key_env(monkeypatch)
    captured = _capture_build(monkeypatch, sdk)
    env_file = write_env(tmp_path, **(env or {"MOONSHOT_API_KEY": SECRET}))
    out = tmp_path / name
    args = run_args("G0", out, model=model, reps=1, env_file=str(env_file),
                    budget_file=str(tmp_path / "budget.json"))
    rc = cli.cmd_run(args, oracle_factory=lambda t, term: FakeOracle(True))
    return out, captured, rc


def _cell(out):
    path = out.joinpath(*CELL) / "result.json"
    return json.loads(path.read_text())


# ── 1. real path: request params, base_url, key hygiene ──────────────
def test_kimi_real_path_moonshot_request_params(tmp_path, monkeypatch, capsys):
    sdk = FakeSDK(chat_handler=sequence_handler([chat_response(RUST, usage=_usage())]))
    out, captured, rc = _run(tmp_path, monkeypatch, sdk)
    assert rc == 0

    call = sdk.chat.completions.calls[0]
    assert captured["base_url"] == MOONSHOT_BASE_URL
    assert captured["api_key"] == SECRET
    assert call["model"] == "kimi-k3"
    assert call["reasoning_effort"] == "high"
    assert "temperature" not in call
    assert "thinking" not in call
    assert "thinking" not in (call.get("extra_body") or {})

    # The frozen registry policy is carried into the MANIFEST.
    manifest = json.loads((out / "MANIFEST.json").read_text())
    assert manifest["model_policy"]["channel"] == "moonshot-direct"
    assert manifest["run_params"]["thinking"] == "always"
    assert manifest["run_params"]["reasoning_effort"] == "high"
    assert manifest["run_params"]["supports_seed"] is False

    # The key value never reaches stdout or any run artifact.
    captured_io = capsys.readouterr()
    assert SECRET not in captured_io.out + captured_io.err
    for path in out.rglob("*"):
        if path.is_file():
            assert SECRET not in path.read_text(errors="ignore"), path


# ── 2. reasoning_content is recorded, never the reply text ───────────
def test_kimi_reasoning_content_recorded_separately(tmp_path, monkeypatch):
    sdk = FakeSDK(chat_handler=sequence_handler([
        chat_response(RUST, reasoning="SECRET-REASONING", usage=_usage())]))
    out, _captured, rc = _run(tmp_path, monkeypatch, sdk)
    assert rc == 0

    log = [json.loads(line) for line in
           (out / "evidence" / "requests.jsonl").read_text().splitlines() if line.strip()]
    assert "SECRET-REASONING" not in json.dumps(log[0])
    assert log[0]["reasoning_sha256"]
    assert log[0]["reasoning_chars"] == len("SECRET-REASONING")
    assert "reasoning_content" not in log[0]
    assert "SECRET-REASONING" not in log[0]["content"]

    candidate = out.joinpath(*CELL) / "candidate.rs"
    assert "SECRET-REASONING" not in candidate.read_text(errors="ignore")
    audit = (out / "audit.jsonl").read_text(errors="ignore")
    assert "SECRET-REASONING" not in audit

    assert _cell(out)["calls"][0]["usage"]["reasoning"] == 3


# ── 3. truncation retry reuses the R2 mechanism ──────────────────────
def test_kimi_truncation_retry(tmp_path, monkeypatch):
    sdk = FakeSDK(chat_handler=sequence_handler([
        chat_response("", finish_reason="length", usage=_usage()),
        chat_response(RUST, finish_reason="stop", usage=_usage()),
    ]))
    out, _captured, rc = _run(tmp_path, monkeypatch, sdk)
    assert rc == 0
    assert len(sdk.chat.completions.calls) == 2
    assert sdk.chat.completions.calls[0]["max_tokens"] == 32768
    assert sdk.chat.completions.calls[1]["max_tokens"] == 65536
    call = _cell(out)["calls"][0]
    assert call["truncation_retry"] is True
    assert len(call["finish_reasons"]) == 2


# ── 4. Kimi needs MOONSHOT_API_KEY; GPT still needs OPENCODE_API_KEY ─
def test_key_requirements_are_channel_specific(tmp_path):
    kimi = resolve_model(build_registry(), "Kimi")
    gpt = resolve_model(build_registry(), "GPT 6 Luna")
    kimi_env = CHANNELS[kimi.channel].api_key_env
    gpt_env = CHANNELS[gpt.channel].api_key_env
    assert kimi_env == "MOONSHOT_API_KEY"
    assert gpt_env == "OPENCODE_API_KEY"

    # MOONSHOT_API_KEY alone constructs Kimi.
    assert channels.key_for(kimi, {"MOONSHOT_API_KEY": "k"}, kimi_env) == "k"
    client = channels.build_client(kimi, params_for_model(kimi), budget=None,
                                   evidence_dir=tmp_path, api_key="k",
                                   sdk_client=FakeSDK())
    assert client.base_url == MOONSHOT_BASE_URL

    # OPENCODE_API_KEY is irrelevant to Kimi: it still asks for MOONSHOT_API_KEY.
    with pytest.raises(ChannelUnavailable, match="MOONSHOT_API_KEY"):
        channels.key_for(kimi, {"OPENCODE_API_KEY": "k"}, kimi_env)
    # MOONSHOT_API_KEY is irrelevant to GPT: it still asks for OPENCODE_API_KEY.
    with pytest.raises(ChannelUnavailable, match="OPENCODE_API_KEY"):
        channels.key_for(gpt, {"MOONSHOT_API_KEY": "k"}, gpt_env)


# ── 5. models probe --dry-run lists the new Kimi channel ─────────────
def test_models_probe_dry_run_lists_kimi_moonshot(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    env = write_env(tmp_path, MOONSHOT_API_KEY="SECRET-PROBE-KIMI")
    rc = cli.main(["models", "probe", "--dry-run", "--env-file", str(env)])
    assert rc == 0
    text = capsys.readouterr().out
    assert "SECRET-PROBE-KIMI" not in text
    document = json.loads(text)
    kimi = next(m for m in document["models"] if m["model_id"] == "kimi-k3")
    assert kimi["channel"] == "moonshot-direct"
    assert kimi["base_url"] == MOONSHOT_BASE_URL
    assert kimi["thinking"] == "always"
    assert kimi["reasoning_effort"] == "high"
    assert kimi["api_key_env"] == "MOONSHOT_API_KEY"
    assert kimi["api_key_present"] is True


# ── 6. GPT 6 Luna is unchanged (still OpenCode, effort medium) ───────
def test_gpt_still_opencode_responses_medium(tmp_path, monkeypatch):
    sdk = FakeSDK(responses_handler=sequence_responses_handler([RUST]))
    out, captured, rc = _run(tmp_path, monkeypatch, sdk, model="GPT 6 Luna",
                             env={"OPENCODE_API_KEY": SECRET}, name="run_gpt")
    assert rc == 0
    call = sdk.responses.calls[0]
    assert captured["base_url"] == OPENCODE_BASE_URL
    assert call["reasoning"] == {"effort": "medium"}
    assert "temperature" not in call


# ── 7. probe real path varies Kimi's top-level reasoning_effort ──────
def _kimi_effort_handler(kwargs):
    reasoning = {"low": 10, "high": 30}[kwargs["reasoning_effort"]]
    usage = {"prompt_tokens": 1, "completion_tokens": reasoning + 1,
             "completion_tokens_details": {"reasoning_tokens": reasoning}}
    return chat_response(RUST, reasoning="SECRET-REASONING", usage=usage)


def test_models_probe_real_path_kimi_efforts(tmp_path, monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "SECRET-PROBE-KIMI")
    sdk = FakeSDK(chat_handler=_kimi_effort_handler)
    # Only the outer SDK is replaced: the real channels.build_client and
    # DirectChatClient run, so the low variant really sends a top-level low.
    patch_build_client(monkeypatch, sdk)
    kimi = resolve_model(build_registry(), "Kimi")

    out_dir = tmp_path / "probe"
    document = models_probe.probe_run(out_dir, models=[kimi])

    # Default probe, low/high variants, then the nontrivial prompt at high and low.
    assert [call["reasoning_effort"] for call in sdk.chat.completions.calls] == \
        ["high", "low", "high", "high", "low"]
    for call in sdk.chat.completions.calls:
        assert "thinking" not in call
        assert "temperature" not in call
        assert "seed" not in call
        assert "extra_body" not in call

    record = document["models"][0]
    assert record["reasoning_tokens_low"] == 10
    assert record["reasoning_tokens_high"] == 30
    assert record["reasoning_tokens_medium"] is None
    assert record["reasoning_content_present"] is True
    assert record["finish_reason"] == "stop"
    assert record["returned_model"] == "kimi-k3"

    text = (out_dir / "PROBE.json").read_text()
    assert "SECRET-PROBE-KIMI" not in text
    assert "SECRET-REASONING" not in text


# ── 8. the OpenCode Kimi alias/entry is gone ─────────────────────────
def test_kimi_opencode_alias_and_entry_removed():
    registry = build_registry()
    with pytest.raises(KeyError):
        resolve_model(registry, "kimi-k2.7-code")
    assert not [s for s in registry
                if s.provider == "moonshot" and s.channel == "opencode-go"]
