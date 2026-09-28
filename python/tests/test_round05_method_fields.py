"""T3: CellResult.extra, generic _merge_cell, _budget and method-field schema."""

import json

import pytest

from skelnet import cli
from skelnet.pipeline import CellResult, dumps, result_to_dict
from skelnet.schema import validate_cell

from test_schema import _valid_cell


# ── extra fields ─────────────────────────────────────────────────────
def test_extra_keys_appear_at_top_level():
    cell = CellResult(arm="SKEL", task="t", replicate=0)
    cell.extra = {"skel_verified": False, "rust_calls": 2}
    out = result_to_dict(cell)
    assert out["skel_verified"] is False and out["rust_calls"] == 2


def test_extra_conflict_raises():
    cell = CellResult(arm="SKEL", task="t", replicate=0)
    cell.extra = {"accepted": True}
    with pytest.raises(ValueError):
        dumps(cell)


def test_merge_cell_has_no_whitelist():
    base = _valid_cell()
    cell = CellResult(arm="SKEL", task="t", replicate=0)
    cell.extra = {"skel_verified": True, "rust_attempts": [
        {"call": 1, "stage": "rust", "reply_kind": "program", "compiled": True}]}
    data = cli._merge_cell(base, cell, provider=None, run_params=None)
    assert data["skel_verified"] is True
    assert data["rust_attempts"][0]["compiled"] is True


# ── budget ───────────────────────────────────────────────────────────
def test_budget_per_rep_by_arm():
    assert cli._budget("G0", 5, 1, 2, "llm", 5)["requests_per_task"] == 1
    assert cli._budget("SKEL", 5, 1, 2, "llm", 5)["requests_per_task"] == 5
    assert cli._budget("CIR", 5, 1, 2, "llm", 5)["requests_per_task"] == 5
    assert cli._budget("SKEL", 5, 1, 2, "codegen", 5)["requests_per_task"] == 2
    assert cli._budget("CIR", 5, 1, 3, "codegen", 5)["requests_per_task"] == 3
    assert cli._budget("STATIC", 5, 1, 2, "llm", 5)["requests_per_task"] == 5
    # call_budget None keeps the legacy per-arm formula.
    assert cli._budget("SKEL", 5, 1, 2, "llm", None)["requests_per_task"] == 3


# ── schema method fields ─────────────────────────────────────────────
def test_method_fields_valid():
    cell = _valid_cell()
    cell.update({"skel_verified": True, "skel_status": "PASS",
                 "feedback_mode": "full", "rust_when_unverified": "last",
                 "property_ids": "keep", "rust_compiled": False,
                 "rust_skipped": None, "rust_calls": 2,
                 "rust_attempts": [{"call": 3, "stage": "rust", "reply_kind": "program",
                                    "compiled": False}]})
    assert validate_cell(cell) == []


def test_method_fields_reject_bad_types():
    for key, value in (("skel_verified", "yes"), ("skel_status", 5),
                       ("feedback_mode", 3), ("rust_compiled", "no"),
                       ("rust_calls", "3"), ("rust_attempts", "x")):
        cell = _valid_cell()
        cell[key] = value
        assert validate_cell(cell), key


def test_method_fields_absent_is_fine():
    assert validate_cell(_valid_cell()) == []
