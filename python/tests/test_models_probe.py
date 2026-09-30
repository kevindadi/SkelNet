"""D4: `models probe --dry-run` lists the four experimental models."""

import json

from skelnet.models_probe import probe_dry_run, probe_run
from skelnet.transport import EXPERIMENTAL_MODEL_IDS

from _fake_sdk import TransportOutcome

EXPECTED = set(EXPERIMENTAL_MODEL_IDS)


def test_dry_run_lists_four_models():
    document = probe_dry_run()
    ids = {m["model_id"] for m in document["models"]}
    assert ids == EXPECTED
    for model in document["models"]:
        for key in ("thinking", "reasoning_effort", "max_output_tokens",
                    "supports_seed", "api_key_present"):
            assert key in model, key


class _ProbeClient:
    def set_cell(self, *_args):
        return None

    def complete(self, system, user):
        return TransportOutcome("OK", usage={"prompt_tokens": 1})


def test_probe_run_records_fields_without_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "SECRET-VALUE")
    document = probe_run(tmp_path, client_factory=lambda spec, params: _ProbeClient())
    assert (tmp_path / "PROBE.json").exists()
    text = (tmp_path / "PROBE.json").read_text()
    assert "SECRET-VALUE" not in text
    for record in document["models"]:
        assert record["probed"] is True
        assert "returned_model" in record and "usage" in record
