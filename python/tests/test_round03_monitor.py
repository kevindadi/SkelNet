"""T5 (round 3b): O4 mapping, thread counting, extra_sync and categories."""

import json
from pathlib import Path

from skelnet.rusttools.monitor import (binding_of, build_mapping, evaluate_o4,
                                       reference_thread_count, residual_spawns,
                                       trace_thread_count)
from skelnet.rusttools.runner import ToolRunner

from round03_helpers import (DEFAULT_RESOURCES, DEFAULT_TRACE, EMPTY_TRACE,
                             FakeTools)

FIXTURE = Path(__file__).parent / "fixtures" / "round03" / "abba_2lock"


def _contract():
    return json.loads((FIXTURE / "contract.json").read_text(encoding="utf-8"))


def _fixture_gold():
    return json.loads((FIXTURE / "gold.cir.json").read_text(encoding="utf-8"))


def _gold(**counts):
    resources = []
    for kind, number in counts.items():
        for index in range(number):
            resources.append({"name": f"{kind.lower()}{index}", "kind": "sync",
                              "type": kind})
    return {"modules": [{"resources": resources}]}


def _evaluate(tmp_path, report, *, resources=None, gold=None, traces=None,
              annotated=None):
    task_dir = tmp_path / "task"
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "contract.json").write_text(json.dumps(_contract()), encoding="utf-8")
    (task_dir / "gold.cir.json").write_text(json.dumps(gold or _fixture_gold()),
                                            encoding="utf-8")
    tools = ToolRunner(runner=FakeTools(
        monitor_report=report, resources=resources if resources is not None else DEFAULT_RESOURCES,
        traces=traces, annotated=annotated), toolchain=None)
    return evaluate_o4(tools, tmp_path / "o4", "fn main() {}\n", task_dir=task_dir,
                       instrument_bin="concir-instrument",
                       backend_bin="concir-backend", concir_sync_path="x", runs=1)


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
    assert reference_thread_count(_fixture_gold()) == 2


def test_trace_thread_count_uses_tags_and_spawn_events(tmp_path):
    traces = tmp_path / "traces"
    traces.mkdir()
    (traces / "run0.jsonl").write_text(
        "\n".join(json.dumps(e) for e in DEFAULT_TRACE), encoding="utf-8")
    assert trace_thread_count(traces) == 2
    (traces / "run0.jsonl").write_text("", encoding="utf-8")
    assert trace_thread_count(traces) == 0


def test_residual_spawns_detection():
    assert residual_spawns("let h = thread::spawn(move || {});") == ["thread::spawn"]
    assert residual_spawns("s.spawn(move || {});") == [".spawn("]
    assert residual_spawns("thread::scope(|s| {});") == ["thread::scope"]
    assert residual_spawns("cir_trace::spawn(\"t1#1\", f);") == []
    assert residual_spawns("__skelnet_serial_spawn(move || f())") == []


# ── property classification ──────────────────────────────────────────
def test_safety_fail_is_monitor_fail(tmp_path):
    report = {"status": "fail", "properties": [
        {"id": "inv", "kind": "safety", "status": "FAIL"}]}
    result = _evaluate(tmp_path, report)
    assert result.status == "fail" and result.category == "monitor_fail"


def test_not_observed(tmp_path):
    report = {"status": "ok", "properties": [
        {"id": "p", "kind": "reachable", "status": "not_observed"}]}
    result = _evaluate(tmp_path, report)
    assert result.category == "not_observed"


def test_unmapped(tmp_path):
    report = {"status": "ok", "properties": [
        {"id": "p", "kind": "reachable", "status": "unmapped"}]}
    result = _evaluate(tmp_path, report)
    assert result.category == "unmapped"


def test_all_unsupported(tmp_path):
    report = {"status": "ok", "properties": [
        {"id": "p", "kind": "reachable", "status": "unsupported"}]}
    result = _evaluate(tmp_path, report)
    assert result.status == "unsupported"


# ── thread counting (M1) ─────────────────────────────────────────────
def test_no_spawn_resources_but_trace_tags_is_not_thread_loss(tmp_path):
    resources = [r for r in DEFAULT_RESOURCES if r["kind"] != "Spawn"]
    result = _evaluate(tmp_path, {"status": "ok", "properties": []},
                       resources=resources)
    assert result.status == "pass", result.detail


def test_no_workers_is_design_loss(tmp_path):
    resources = [r for r in DEFAULT_RESOURCES if r["kind"] != "Spawn"]
    result = _evaluate(tmp_path, {"status": "ok", "properties": []},
                       resources=resources, traces=[EMPTY_TRACE])
    assert result.status == "fail" and result.category == "design_loss"
    assert result.detail == "threads: 0 < reference 2"


def test_residual_scope_is_instrument_unsupported(tmp_path):
    annotated = "fn main() { std::thread::scope(|s| { s.spawn(|| {}); }); }\n"
    report = {"status": "ok", "properties": [
        {"id": "p", "kind": "reachable", "status": "not_observed"}]}
    result = _evaluate(tmp_path, report, traces=[DEFAULT_TRACE], annotated=annotated)
    assert result.status == "unsupported"
    assert result.category == "instrument_unsupported"
    assert "thread::scope" in result.detail


def test_residual_spawn_with_unmapped_is_instrument_unsupported(tmp_path):
    annotated = "fn main() { handles.push(thread::spawn(|| {})); }\n"
    report = {"status": "ok", "properties": [
        {"id": "p", "kind": "reachable", "status": "unmapped"}]}
    result = _evaluate(tmp_path, report, traces=[DEFAULT_TRACE], annotated=annotated)
    assert result.status == "unsupported"
    assert result.category == "instrument_unsupported"


def test_residual_spawn_keeps_monitor_fail(tmp_path):
    annotated = "fn main() { handles.push(thread::spawn(|| {})); }\n"
    report = {"status": "fail", "properties": [
        {"id": "inv", "kind": "safety", "status": "FAIL"}]}
    result = _evaluate(tmp_path, report, traces=[DEFAULT_TRACE], annotated=annotated)
    assert result.status == "fail" and result.category == "monitor_fail"
    assert "instrument_unsupported" in result.data["categories"]


# ── extra_sync by type (M2) ──────────────────────────────────────────
def test_pair_mutex_condvar_matches_gold(tmp_path):
    resources = [{"name": "pair_mutex0#1", "kind": "Mutex"},
                 {"name": "pair_condvar0#2", "kind": "Condvar"}]
    result = _evaluate(tmp_path, {"status": "ok", "properties": []},
                       resources=resources, gold=_gold(Mutex=1, Condvar=1),
                       traces=[DEFAULT_TRACE])
    assert result.status == "pass", result.detail


def test_extra_static_mutex(tmp_path):
    resources = [{"name": "a_mutex0#86", "kind": "Mutex"},
                 {"name": "b_mutex0#124", "kind": "Mutex"},
                 {"name": "g_mutex0#9", "kind": "Mutex"}]
    result = _evaluate(tmp_path, {"status": "ok", "properties": []},
                       resources=resources, gold=_gold(Mutex=2),
                       traces=[DEFAULT_TRACE])
    assert result.category == "design_loss"
    assert result.detail.startswith("extra_sync: Mutex 3 > 2")
    assert "g_mutex0#9" in result.detail


def test_extra_channel_is_not_extra_sync(tmp_path):
    resources = [{"name": "a_mutex0#86", "kind": "Mutex"},
                 {"name": "b_mutex0#124", "kind": "Mutex"},
                 {"name": "tx#5", "kind": "Channel"}]
    result = _evaluate(tmp_path, {"status": "ok", "properties": []},
                       resources=resources, gold=_gold(Mutex=2),
                       traces=[DEFAULT_TRACE])
    assert result.status == "pass", result.detail


def test_safety_fail_beats_extra_sync(tmp_path):
    resources = [{"name": "a_mutex0#86", "kind": "Mutex"},
                 {"name": "b_mutex0#124", "kind": "Mutex"},
                 {"name": "g_mutex0#9", "kind": "Mutex"}]
    report = {"status": "fail", "properties": [
        {"id": "inv", "kind": "safety", "status": "FAIL"}]}
    result = _evaluate(tmp_path, report, resources=resources,
                       gold=_gold(Mutex=2), traces=[DEFAULT_TRACE])
    assert result.category == "monitor_fail"
    assert "monitor_fail" in result.data["categories"]
    assert "design_loss" in result.data["categories"]


def test_unmapped_program_resources_recorded(tmp_path):
    resources = [{"name": "weird_mutex0#7", "kind": "Mutex"}]
    result = _evaluate(tmp_path, {"status": "ok", "properties": []},
                       resources=resources, gold=_gold(Mutex=1),
                       traces=[DEFAULT_TRACE])
    assert "weird_mutex0#7" in result.data["unmapped_program_resources"]


def test_mapping_passed_to_monitor(tmp_path):
    resources = DEFAULT_RESOURCES
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "contract.json").write_text(json.dumps(_contract()), encoding="utf-8")
    (task_dir / "gold.cir.json").write_text(json.dumps(_fixture_gold()), encoding="utf-8")
    tools = FakeTools(resources=resources)
    runner = ToolRunner(runner=tools, toolchain=None)
    evaluate_o4(runner, tmp_path / "o4", "fn main() {}\n", task_dir=task_dir,
                instrument_bin="concir-instrument", backend_bin="concir-backend",
                concir_sync_path="x", runs=1)
    monitor = [c for c in tools.calls if Path(c[0]).name == "concir-backend"][0]
    mapping_path = Path(monitor[monitor.index("--mapping") + 1])
    expected = build_mapping([r["name"] for r in resources], _contract())
    assert json.loads(mapping_path.read_text())["mapping"] == expected


def test_missing_contract_is_not_run(tmp_path):
    tools = ToolRunner(runner=FakeTools(), toolchain=None)
    result = evaluate_o4(tools, tmp_path, "fn main() {}\n", task_dir=None,
                         instrument_bin="concir-instrument",
                         backend_bin="concir-backend", concir_sync_path="x")
    assert result.status == "not_run" and result.category == "no_contract"
