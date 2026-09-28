"""M7: models probe honours --env-file and reports honest probe results."""

import json

from skelnet import cli
from skelnet.models_probe import probe_run

from _fake_sdk import TransportOutcome


def test_dry_run_env_file_reports_key_presence(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("OPENCODE_API_KEY=SECRET-PROBE\n", encoding="utf-8")

    rc = cli.main(["models", "probe", "--dry-run", "--env-file", str(env)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "SECRET-PROBE" not in captured.out
    document = json.loads(captured.out)
    by_id = {m["model_id"]: m for m in document["models"]}
    assert by_id["gpt-6-luna"]["api_key_present"] is True
    assert by_id["kimi-k3"]["api_key_present"] is True
    assert by_id["deepseek-flash"]["api_key_present"] is False


class _ProbeClient:
    def __init__(self, params):
        self.params = params

    def set_cell(self, *_args):
        return None

    def complete(self, system, user):
        effort = getattr(self.params, "reasoning_effort", None)
        reasoning = {"low": 10, "medium": 20}.get(effort, 5)
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
    for model_id in ("gpt-6-luna", "kimi-k3"):
        record = by_id[model_id]
        assert record["reasoning_tokens_low"] == 10
        assert record["reasoning_tokens_medium"] == 20
        assert record["thinking_accepted"] is True
    for record in document["models"]:
        assert "requires_stream" in record
