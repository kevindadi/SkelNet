"""M7: models probe honours --env-file and reports honest probe results."""

import json
from types import SimpleNamespace

from skelnet import cli
from skelnet.models_probe import probe_run
from skelnet.transport import build_registry, resolve_model

from _fake_sdk import TransportOutcome


def test_dry_run_env_file_reports_key_presence(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("OPENCODE_API_KEY=SECRET-PROBE\n"
                   "MOONSHOT_API_KEY=SECRET-MOON\n", encoding="utf-8")

    rc = cli.main(["models", "probe", "--dry-run", "--env-file", str(env)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "SECRET-PROBE" not in captured.out
    assert "SECRET-MOON" not in captured.out
    document = json.loads(captured.out)
    by_id = {m["model_id"]: m for m in document["models"]}
    assert by_id["gpt-6-luna"]["api_key_present"] is True
    # Kimi is on the Moonshot channel now: its key is MOONSHOT_API_KEY.
    assert by_id["kimi-k3"]["api_key_present"] is True
    assert by_id["kimi-k3"]["channel"] == "moonshot-direct"
    assert by_id["kimi-k3"]["base_url"] == "https://api.moonshot.cn/v1"
    assert by_id["deepseek-flash"]["api_key_present"] is False


class _ProbeClient:
    def __init__(self, params):
        self.params = params

    def set_cell(self, *_args):
        return None

    def complete(self, system, user):
        effort = getattr(self.params, "reasoning_effort", None)
        reasoning = {"low": 10, "medium": 20, "high": 30}.get(effort, 5)
        usage = {"prompt_tokens": 1, "completion_tokens": reasoning + 1,
                 "completion_tokens_details": {"reasoning_tokens": reasoning}}
        return TransportOutcome("OK", usage=usage)


def test_probe_run_records_effort_and_no_key(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "SECRET-PROBE")
    document = probe_run(tmp_path,
                         client_factory=lambda spec, params: _ProbeClient(params))
    text = (tmp_path / "PROBE.json").read_text()
    assert "SECRET-PROBE" not in text
    by_id = {m["model_id"]: m for m in document["models"]}
    gpt = by_id["gpt-6-luna"]
    assert gpt["reasoning_tokens_low"] == 10
    assert gpt["reasoning_tokens_medium"] == 20
    assert gpt["thinking_accepted"] is True
    # Kimi probes low/high (its strengths are low/high/max).
    kimi = by_id["kimi-k3"]
    assert kimi["reasoning_tokens_low"] == 10
    assert kimi["reasoning_tokens_high"] == 30
    assert kimi["reasoning_tokens_medium"] is None
    assert kimi["thinking_accepted"] is True
    for record in document["models"]:
        assert "requires_stream" in record


def _outcome(text="OK", usage=None, reasoning_content=None):
    return SimpleNamespace(text=text, usage=usage, reasoning_content=reasoning_content,
                           response_model=None, finish_reason="stop", seed=None)


def _factory(handler):
    def build(_spec, params):
        class _Client:
            def set_cell(self, *_args):
                return None

            def complete(self, system, user):
                return handler(params)
        return _Client()
    return build


def test_thinking_accepted_rules(tmp_path):
    spec = resolve_model(build_registry(), "DeepSeek Flash")
    reasoning_usage = {"prompt_tokens": 1, "completion_tokens": 5,
                       "completion_tokens_details": {"reasoning_tokens": 3}}
    doc = probe_run(tmp_path / "reasoning", models=[spec],
                    client_factory=_factory(lambda _p: _outcome(usage=reasoning_usage)))
    assert doc["models"][0]["thinking_accepted"] is True

    doc = probe_run(tmp_path / "content", models=[spec],
                    client_factory=_factory(lambda _p: _outcome(reasoning_content="think")))
    assert doc["models"][0]["thinking_accepted"] is True

    zero_usage = {"prompt_tokens": 1, "completion_tokens": 2,
                  "completion_tokens_details": {"reasoning_tokens": 0}}
    doc = probe_run(tmp_path / "zero", models=[spec],
                    client_factory=_factory(lambda _p: _outcome(usage=zero_usage)))
    assert doc["models"][0]["thinking_accepted"] is None


def test_thinking_accepted_false_on_error(tmp_path):
    spec = resolve_model(build_registry(), "DeepSeek Flash")

    def build(_spec, _params):
        class _Client:
            def set_cell(self, *_args):
                return None

            def complete(self, system, user):
                raise RuntimeError("boom")
        return _Client()

    doc = probe_run(tmp_path, models=[spec], client_factory=build)
    assert doc["models"][0]["thinking_accepted"] is False


def test_requires_stream_rules(tmp_path):
    spec = resolve_model(build_registry(), "Qwen")
    assert spec.channel == "dashscope-direct"
    usage = {"prompt_tokens": 1, "completion_tokens": 5,
             "completion_tokens_details": {"reasoning_tokens": 3}}

    def stream_factory(*, nonstream_ok, stream_ok):
        def build(_spec, params):
            ok = stream_ok if params.stream else nonstream_ok

            class _Client:
                def set_cell(self, *_args):
                    return None

                def complete(self, system, user):
                    if not ok:
                        raise RuntimeError("boom")
                    return _outcome(usage=usage)
            return _Client()
        return build

    doc = probe_run(tmp_path / "plain", models=[spec],
                    client_factory=stream_factory(nonstream_ok=True, stream_ok=True))
    assert doc["models"][0]["requires_stream"] is False

    doc = probe_run(tmp_path / "fallback", models=[spec],
                    client_factory=stream_factory(nonstream_ok=False, stream_ok=True))
    assert doc["models"][0]["requires_stream"] is True

    doc = probe_run(tmp_path / "both_fail", models=[spec],
                    client_factory=stream_factory(nonstream_ok=False, stream_ok=False))
    assert doc["models"][0]["requires_stream"] is None
