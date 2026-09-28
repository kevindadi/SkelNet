"""T5: monitor feedback blocking rules and disclosure filtering."""

import json
from pathlib import Path

from skelnet.rusttools.monitor_feedback import (run_monitor_feedback,
                                                render_monitor_feedback)
from skelnet.rusttools.runner import ToolRunner

from round03_helpers import (DEFAULT_RESOURCES, DEFAULT_TRACE, FakeTools, ns)


def _task(tmp_path, *, goal: str = "keep the lock order", gold=None):
    task = tmp_path / "task"
    task.mkdir(parents=True, exist_ok=True)
    contract = {
        "goal": goal,
        "properties": [{"id": "safety-main", "kind": "safety",
                        "formula": "holds_all(main::a)"}],
    }
    (task / "contract.json").write_text(json.dumps(contract), encoding="utf-8")
    gold_doc = gold if gold is not None else {
        "modules": [{"resources": [
            {"name": "a", "kind": "sync", "type": "Mutex"},
            {"name": "b", "kind": "sync", "type": "Mutex"},
        ]}]
    }
    (task / "gold.cir.json").write_text(json.dumps(gold_doc), encoding="utf-8")
    return task


def _report(props):
    return {"status": "ok", "properties": props}


def _run(tmp_path, report, *, resources=None, annotated=None, fake_kwargs=None):
    task = _task(tmp_path)
    runner = FakeTools(monitor_report=report,
                       resources=resources if resources is not None else DEFAULT_RESOURCES,
                       traces=[DEFAULT_TRACE], annotated=annotated,
                       **(fake_kwargs or {}))
    tools = ToolRunner(runner=runner, toolchain=None)
    result = run_monitor_feedback(
        tools, tmp_path / "feedback", "fn main() {}\n", task_dir=task,
        runs=1, timeout=5)
    return result


def test_monitor_safety_fail_blocks(tmp_path):
    result = _run(tmp_path, _report([
        {"id": "safety-main", "kind": "safety", "source": "properties",
         "req": "R1", "status": "FAIL", "detail": "both locks held"},
    ]))
    assert result.blocking
    assert "safety-main" in result.feedback
    assert "FAIL" in result.feedback


def test_monitor_not_observed_and_unmapped_block(tmp_path):
    observed = _run(tmp_path / "obs", _report([
        {"id": "preserved:t1", "kind": "preserved", "source": "preserved",
         "req": "R2", "status": "not_observed", "detail": "never ran"},
    ]))
    unmapped = _run(tmp_path / "un", _report([
        {"id": "reachable:t2", "kind": "reachable", "source": "preserved",
         "req": "R3", "status": "unmapped", "detail": "no such name"},
    ]))
    assert observed.blocking and unmapped.blocking


def test_monitor_deferred_and_unsupported_do_not_block(tmp_path):
    result = _run(tmp_path, _report([
        {"id": "later", "kind": "deadlock_free", "source": "properties",
         "req": "R4", "status": "deferred", "detail": None},
        {"id": "skip", "kind": "safety", "source": "properties",
         "req": "R5", "status": "unsupported", "detail": "not checked"},
    ]))
    assert not result.blocking


def test_monitor_instrument_unsupported_does_not_block(tmp_path):
    result = _run(
        tmp_path, _report([
            {"id": "later", "kind": "reachable", "source": "preserved",
             "req": "R1", "status": "PASS_bounded", "detail": None},
        ]),
        annotated="fn main() { thread::spawn(|| {}); }\n")
    assert result.category == "instrument_unsupported"
    assert not result.blocking
    assert "monitor 无法插桩这种写法" in result.feedback


def test_monitor_timeout_blocks(tmp_path):
    task = _task(tmp_path)

    def run(cmd, cwd, timeout, env):
        cmd = [str(c) for c in cmd]
        if Path(cmd[0]).name == "concir-instrument":
            out = Path(cmd[cmd.index("--out") + 1])
            out.mkdir(parents=True, exist_ok=True)
            (out / "annotated.rs").write_text("fn main() {}\n", encoding="utf-8")
            (out / "resources.json").write_text(
                json.dumps({"resources": []}), encoding="utf-8")
            return ns(0, "", "")
        if "build" in cmd:
            binary = Path(cwd) / "target" / "debug" / "o4_probe"
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_text("", encoding="utf-8")
            return ns(0, "", "")
        raise __import__("subprocess").TimeoutExpired(cmd, timeout)

    result = run_monitor_feedback(
        ToolRunner(runner=run, toolchain=None), tmp_path / "fb",
        "fn main() {}\n", task_dir=task, runs=1, timeout=5)
    assert result.blocking
    assert "timeout" in result.feedback


def test_monitor_feedback_drops_reference_design_and_goal(tmp_path):
    """A goal-bearing contract and a design_loss gold must not leak."""
    task = _task(
        tmp_path,
        goal="GOAL_LEAK holds_all(main::a) function_completed completed(main::t1)",
        gold={"modules": [{"resources": []}]},
    )
    report = _report([
        {"id": "safety-main", "kind": "safety", "source": "properties",
         "req": "R1", "status": "FAIL",
         "detail": "violated holds_all(main::a) and function_completed completed(t1) goal"},
    ])
    runner = FakeTools(
        monitor_report=report, resources=DEFAULT_RESOURCES, traces=[DEFAULT_TRACE])
    result = run_monitor_feedback(
        ToolRunner(runner=runner, toolchain=None), tmp_path / "feedback",
        "fn main() {}\n", task_dir=task, runs=1, timeout=5)
    text = result.feedback
    for forbidden in ("holds_all(", "function_completed", "completed(",
                      "design_loss", "extra_sync", "reference", "gold", "GOAL_LEAK"):
        assert forbidden not in text, forbidden
    assert "goal" not in text.lower()
    # The reference-design failure is real, and it must not decide acceptance.
    assert result.category == "monitor_fail" or result.blocking
    assert result.blocking  # the safety FAIL still blocks


def test_opaque_property_ids_hide_the_raw_id(tmp_path):
    result = run_monitor_feedback(
        ToolRunner(runner=FakeTools(
            monitor_report=_report([
                {"id": "safety-main", "kind": "safety", "source": "properties",
                 "req": "R1", "status": "FAIL", "detail": "both locks"},
            ]),
            resources=DEFAULT_RESOURCES, traces=[DEFAULT_TRACE]), toolchain=None),
        tmp_path / "feedback", "fn main() {}\n", task_dir=_task(tmp_path),
        property_ids="opaque", runs=1, timeout=5)
    assert "safety-main" not in result.feedback
    assert "id: P1" in result.feedback
