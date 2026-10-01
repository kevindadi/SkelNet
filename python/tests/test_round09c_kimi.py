"""R9c: Kimi moves from ``kimi-k3`` to ``kimi-k2.7-code``.

The model cannot disable thinking, so the Moonshot channel sends
``extra_body={"thinking": {"type": "enabled"}}`` and no ``reasoning_effort``.
DeepSeek, Qwen and GPT must be byte-identical to ``origin/main`` (the golden
file ``fixtures/round09c/golden_kwargs.json`` was captured there).
"""

import json
import tempfile
from pathlib import Path

import pytest

from skelnet import channels, cli, report
from skelnet.params import params_for_model
from skelnet.transport import EXPERIMENTAL_MODEL_IDS, build_registry, resolve_model

from _fake_sdk import (FakeSDK, RUST, chat_response, patch_build_client,
                       responses_response, sequence_handler, write_env)

SECRET = "SECRET-KIMI-9C"
FIXTURES = Path(__file__).parent / "fixtures" / "round09c"
GOLDEN = json.loads((FIXTURES / "golden_kwargs.json").read_text(encoding="utf-8"))


class _Budget:
    def reserve(self) -> None:
        return None

    def add_tokens(self, _tokens) -> None:
        return None


def _clear_key_env(monkeypatch):
    for key in ("OPENCODE_API_KEY", "MOONSHOT_API_KEY"):
        monkeypatch.setenv(key, "x")
        monkeypatch.delenv(key)


def _fake_oracle_factory(**kwargs):
    from skelnet.oracle import FakeOracle
    return lambda task_dir, terminal: FakeOracle(True)


# ── 1. real entry (cli.main) sends the frozen Kimi payload ───────────────

def test_kimi_run_request_kwargs(tmp_path, monkeypatch, capsys):
    _clear_key_env(monkeypatch)
    monkeypatch.setattr(cli, "default_oracle_factory", _fake_oracle_factory)
    sdk = FakeSDK(chat_handler=sequence_handler([
        chat_response(RUST, usage={"prompt_tokens": 5, "completion_tokens": 3})]))
    patch_build_client(monkeypatch, sdk)
    env = write_env(tmp_path, MOONSHOT_API_KEY=SECRET)
    out = tmp_path / "run"

    rc = cli.main(["run", "--arm", "G0", "--model", "Kimi",
                   "--tasks", "lock-order/abba_2lock", "--reps", "1",
                   "--rounds", "1", "--out", str(out),
                   "--env-file", str(env),
                   "--budget-file", str(tmp_path / "budget.json")])
    assert rc == 0

    call = sdk.chat.completions.calls[0]
    assert call["model"] == "kimi-k2.7-code"
    assert call["extra_body"] == {"thinking": {"type": "enabled"}}
    assert call["max_tokens"] == 32768
    for forbidden in ("reasoning_effort", "temperature", "top_p", "n",
                      "presence_penalty", "frequency_penalty", "seed"):
        assert forbidden not in call, forbidden

    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err


# ── 2. DeepSeek / Qwen / GPT are byte-identical to origin/main ───────────

def _capture(model: str) -> dict:
    spec = resolve_model(build_registry(), model)
    sdk = FakeSDK(chat_handler=lambda k: chat_response(RUST),
                  responses_handler=lambda k: responses_response(RUST))
    client = channels.build_client(spec, params_for_model(spec), budget=_Budget(),
                                   evidence_dir=Path(tempfile.mkdtemp()),
                                   api_key="x", sdk_client=sdk)
    client.set_cell("lock-order/abba_2lock", 0)
    client.complete("SYS", "USER")
    call = (sdk.responses.calls or sdk.chat.completions.calls)[0]
    for key in ("messages", "input", "instructions", "extra_headers"):
        call.pop(key, None)
    return call


# R9d-P4 makes Qwen stream by default, so only DeepSeek and GPT are still
# byte-identical to the origin/main golden; Qwen/Kimi streaming is asserted in
# test_round09d_streaming.py.
@pytest.mark.parametrize("model", ["DeepSeek Flash", "GPT 6 Luna"])
def test_unchanged_models_match_main_golden(model):
    assert _capture(model) == GOLDEN[model]


# ── 3. kimi-k3 is refused, not silently remapped ─────────────────────────

def test_kimi_k3_run_refused(tmp_path, monkeypatch, capsys):
    _clear_key_env(monkeypatch)
    env = write_env(tmp_path, MOONSHOT_API_KEY=SECRET)
    rc = cli.main(["run", "--arm", "G0", "--model", "kimi-k3",
                   "--tasks", "lock-order/abba_2lock", "--reps", "1",
                   "--rounds", "1", "--out", str(tmp_path / "void"),
                   "--env-file", str(env)])
    assert rc != 0
    err = capsys.readouterr().err
    assert "kimi-k3" in err and "kimi-k2.7-code" in err
    assert not (tmp_path / "void" / "MANIFEST.json").exists()


# ── 4. probe --dry-run lists the new Kimi policy ─────────────────────────

def test_probe_dry_run_lists_new_kimi(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    env = write_env(tmp_path, MOONSHOT_API_KEY=SECRET)
    # Round 9e: the experimental set is GPT / Cursor Agent / DeepSeek / Qwen.
    assert cli.main(["models", "probe", "--dry-run", "--env-file", str(env)]) == 0
    ids = {m["model_id"] for m in json.loads(capsys.readouterr().out)["models"]}
    assert set(EXPERIMENTAL_MODEL_IDS) == ids
    assert "glm-5.3-flash" in ids and "kimi-k2.7-code" not in ids
    # Kimi is still probeable explicitly (Moonshot channel).
    assert cli.main(["models", "probe", "--dry-run", "--models", "kimi-k2.7-code",
                     "--env-file", str(env)]) == 0
    text = capsys.readouterr().out
    assert SECRET not in text
    document = json.loads(text)
    kimi = next(m for m in document["models"] if m["model_id"] == "kimi-k2.7-code")
    assert kimi["display_name"] == "Kimi"
    assert kimi["channel"] == "moonshot-direct"
    assert kimi["thinking"] == "always"
    assert kimi["reasoning_effort"] is None


# ── 5. report's models table shows the new Kimi column with data ─────────

def _load_synth():
    import importlib.util
    path = Path(__file__).parent / "fixtures" / "round08" / "synth.py"
    spec = importlib.util.spec_from_file_location("r9csynth", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_report_models_table_shows_new_kimi(tmp_path):
    synth = _load_synth()
    for model in synth.MODELS:
        if model["slug"] == "kimi":
            model["model_id"] = "kimi-k2.7-code"
            model["reasoning_effort"] = None
    root = tmp_path / "planted"
    synth.make_runs(root, synth.planted_spec())
    runs = sorted(p for p in root.glob("*/*") if (p / "MANIFEST.json").exists())
    ds = report.load_runs(runs, root=root)
    ctx = report.ReportContext(root=root, look=0,
                               planned_units=report.ReportContext.planned_units,
                               bootstrap=500, seed=1)
    payload = report.table_models(ds, ctx)
    row = next(r for r in payload["rows"] if r["model_id"] == "kimi-k2.7-code")
    assert row["family"] == "Kimi"
    assert row["policy"], row
    assert row["truncation"] is not None, row
