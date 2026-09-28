"""T10: round-2 backlog fixes (S1, S2, S3, S5, S6)."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from skelnet import cli
from skelnet.backend import repo_root
from skelnet.oracle import FakeOracle
from skelnet.params import params_for_model
from skelnet.schema import validate_cell
from skelnet.transport import ModelIdentityError

from _fake_sdk import RUST, ScriptedTransportClient, run_args
from test_schema import _valid_cell


# ── S1: ModelIdentityError stops the whole batch ─────────────────────
class _BadModelClient:
    def __init__(self):
        self.calls = 0

    def complete(self, system, user):
        self.calls += 1
        raise ModelIdentityError(
            "response model 'other' is not the requested 'deepseek-flash'")

    def set_cell(self, *args):
        pass

    def new_session(self):
        pass


def test_model_identity_error_fails_the_run(tmp_path):
    out = tmp_path / "run"
    args = run_args("SKEL", out, tasks="lock-order/*", rounds=1, call_budget=5,
                    budget_file=str(tmp_path / "budget.json"))
    client = _BadModelClient()
    rc = cli.cmd_run(args, client_factory=lambda s, o: client,
                     oracle_factory=lambda t, term: FakeOracle(True))
    assert rc == 1
    assert client.calls == 1  # no request after the mismatch
    manifest = json.loads((out / "MANIFEST.json").read_text())
    assert manifest["status"] == "failed"
    assert manifest["failure"] == "model_identity"
    assert not list((out / "cells").rglob("result.json"))


# ── S2: --max-output-tokens default comes from the registry ──────────
def _run_args(argv):
    return cli.build_parser().parse_args(argv)


def test_max_output_tokens_uses_registry_by_default():
    spec = SimpleNamespace(thinking=True, reasoning_effort=None, stream=False,
                           max_output_tokens=12345, max_output_tokens_cap=65536,
                           supports_seed=False)
    args = _run_args(["run", "--arm", "SKEL"])
    params = cli._run_params(args, spec)
    assert params.max_output_tokens == 12345

    args = _run_args(["run", "--arm", "SKEL", "--max-output-tokens", "999"])
    assert cli._run_params(args, spec).max_output_tokens == 999


def test_params_for_model_registry_value():
    spec = SimpleNamespace(max_output_tokens=7777)
    assert params_for_model(spec).max_output_tokens == 7777


# ── S3: --budget-file resolves under the repo root ───────────────────
def test_budget_file_default_is_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = _run_args(["run", "--arm", "G0"])
    assert Path(args.budget_file).is_absolute()
    assert str(args.budget_file).startswith(str(repo_root()))


# ── S5: schema layer types and accepted ──────────────────────────────
def test_layer_field_types_are_checked():
    for layer, key, value in (("O1", "wall_ms", "12"), ("O1", "category", 5),
                              ("O2", "detail", 3)):
        cell = _valid_cell()
        cell["oracle"]["layers"] = {layer: {"status": "pass", "category": None,
                                            "detail": None, "wall_ms": None}}
        cell["oracle"]["layers"][layer][key] = value
        assert validate_cell(cell), (layer, key)


def test_accepted_must_be_bool():
    cell = _valid_cell()
    cell["accepted"] = "yes"
    assert validate_cell(cell)


# ── S6: dry-run lists all four model policies ────────────────────────
def test_dry_run_lists_all_model_policies(capsys, tmp_path):
    args = run_args("G0", tmp_path / "out", tasks="lock-order/abba_2lock")
    args.dry_run = True
    assert cli.cmd_run(args) == 0
    document = json.loads(capsys.readouterr().out)
    policies = document["model_policies"]
    assert len(policies) == 4
    assert all(p["temperature_sent"] is False for p in policies)
    assert "model_policy" in document
