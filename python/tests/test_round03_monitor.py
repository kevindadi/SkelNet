"""T5: O4 resource mapping, design_loss and property classification."""

import json
from pathlib import Path

from skelnet.rusttools.monitor import (binding_of, build_mapping, evaluate_o4,
                                       reference_thread_count)
from skelnet.rusttools.runner import ToolRunner

from round03_helpers import DEFAULT_RESOURCES, FakeTools, ns

FIXTURE = Path(__file__).parent / "fixtures" / "round03" / "abba_2lock"


def _contract():
    return json.loads((FIXTURE / "contract.json").read_text(encoding="utf-8"))


def test_binding_strips_site_and_type_counter():
    assert binding_of("a_mutex0#86") == "a"
    assert binding_of("b_mutex0#124") == "b"
    assert binding_of("t1#200") == "t1"
    assert binding_of("s_condvar0#5") == "s"


def test_build_mapping_uses_measured_names():
    names = [r["name"] for r in DEFAULT_RESOURCES]
    mapping = build_mapping(names, _contract())
    assert mapping == {"a_mutex0#86": "main::a", "b_mutex0#124": "main::b",
                       "t1#200": "main::t1", "t2#354": "main::t2"}


def test_reference_thread_count_from_gold():
    gold = json.loads((FIXTURE / "gold.cir.json").read_text(encoding="utf-8"))
    assert reference_thread_count(gold) == 2


def _evaluate(report, resources=None, gold=None, task_dir=FIXTURE):
    tools = ToolRunner(runner=FakeTools(monitor_report=report,
                                        resources=resources or DEFAULT_RESOURCES),
                       toolchain=None)
    return evaluate_o4(tools, Path("/tmp") / "o4test", "fn main() {}\n",
                       task_dir=task_dir, instrument_bin="concir-instrument",
                       backend_bin="concir-backend", concir_sync_path="x", runs=1)


def test_safety_fail_is_monitor_fail():
    report = {"status": "fail", "properties": [
        {"id": "inv", "kind": "safety", "status": "FAIL"}]}
    result = _evaluate(report)
    assert result.status == "fail" and result.category == "monitor_fail"


def test_not_observed():
    report = {"status": "ok", "properties": [
        {"id": "p", "kind": "reachable", "status": "not_observed"}]}
    result = _evaluate(report)
    assert result.category == "not_observed"


def test_unmapped():
    report = {"status": "ok", "properties": [
        {"id": "p", "kind": "reachable", "status": "unmapped"}]}
    result = _evaluate(report)
    assert result.category == "unmapped"


def test_all_unsupported():
    report = {"status": "ok", "properties": [
        {"id": "p", "kind": "reachable", "status": "unsupported"}]}
    result = _evaluate(report)
    assert result.status == "unsupported"


def test_design_loss_for_missing_threads():
    resources = [r for r in DEFAULT_RESOURCES if r["kind"] != "Spawn"]
    result = _evaluate({"status": "ok", "properties": []}, resources=resources)
    assert result.status == "fail" and result.category == "design_loss"
    assert "threads" in result.detail


def test_design_loss_for_extra_sync():
    resources = DEFAULT_RESOURCES + [{"name": "g_mutex0#9", "kind": "Mutex"}]
    result = _evaluate({"status": "ok", "properties": []}, resources=resources)
    assert result.category == "design_loss"
    assert "extra_sync" in result.detail


def test_missing_contract_is_not_run(tmp_path):
    tools = ToolRunner(runner=FakeTools(), toolchain=None)
    result = evaluate_o4(tools, tmp_path, "fn main() {}\n", task_dir=None,
                         instrument_bin="concir-instrument",
                         backend_bin="concir-backend", concir_sync_path="x")
    assert result.status == "not_run" and result.category == "no_contract"
