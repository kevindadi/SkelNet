"""C1: requirements are rendered from REQUIREMENTS.md, never the task path."""

import json

import pytest

from skelnet import cli
from skelnet.backend import repo_root
from skelnet.oracle import FakeOracle
from skelnet.requirements_render import RequirementsMissing, render_requirements

from _fake_sdk import RUST, ScriptedTransportClient, run_args

TASKS = repo_root() / "benchmarks" / "tasks"
BOUNDARY = ("boundary/rwlock_unsupported", "boundary/async_select_unsupported",
            "boundary/unbounded_int_unknown")


def _task_dirs():
    return sorted(p.parent for p in TASKS.glob("*/*/contract.json"))


def test_render_is_clean_for_non_boundary_tasks():
    for task_dir in _task_dirs():
        rel = str(task_dir.relative_to(TASKS))
        if rel.startswith("boundary/"):
            continue
        text = render_requirements(task_dir, "h0")
        for bad in ("clauses", "contract", "unverifiable", "[U]", "benchmarks/"):
            assert bad not in text, (rel, bad)
        assert rel not in text, rel


def test_boundary_tasks_have_no_requirements_text():
    for rel in BOUNDARY:
        with pytest.raises(RequirementsMissing):
            render_requirements(TASKS / rel, "h0")


def test_boundary_via_cmd_run_sends_nothing(tmp_path):
    out = tmp_path / "run"
    client = ScriptedTransportClient([RUST])
    args = run_args("G0", out, tasks="boundary/*")
    rc = cli.cmd_run(args, client_factory=lambda spec, o: client,
                     oracle_factory=lambda t, term: FakeOracle(True))
    assert rc == 0
    assert client.calls == []  # no LLM request at all
    for path in (out / "cells").rglob("result.json"):
        data = json.loads(path.read_text())
        assert data["status"] == "skipped"
        assert data["skip_reason"] == "no_requirements_text"
