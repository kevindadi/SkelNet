"""B3: the terminal line reaches Shuttle on the oracle and DYNAMIC paths.

Only the outermost subprocess runner is replaced. The fake Shuttle binary
prints schedule markers only when the generated project really contains them,
and prints a wrong last line in one schedule when the program source carries
``SHUTTLE_WRONG``.
"""

import json
from pathlib import Path

from skelnet import cli
from skelnet.oracle import RustOracle, oracle_result_dict
from skelnet.rusttools.shuttle import PCT_MARKER, RANDOM_MARKER

from round03_helpers import ns
from test_round04_baselines import TERMINAL, _Client, _CmdRunner, _in_shuttle, _rust, _source_of

FIXTURE = Path(__file__).parent / "fixtures" / "round03" / "abba_2lock"


def _shuttle_stdout(source: str) -> str:
    if PCT_MARKER not in source or RANDOM_MARKER not in source:
        return ""
    lines = []
    for index in range(4):
        wrong = "SHUTTLE_WRONG" in source and index == 2
        lines += ["DONE t1=0 t2=1" if wrong else TERMINAL, "",
                  PCT_MARKER if index < 2 else RANDOM_MARKER]
    return "\n".join(lines) + "\n"


class _MarkerRunner(_CmdRunner):
    def __call__(self, cmd, cwd, timeout, env):
        cmd = [str(part) for part in cmd]
        cwd = Path(cwd)
        if (Path(cmd[0]).name == "shuttle_probe" or _in_shuttle(cwd)) \
                and "build" not in cmd:
            self.argvs.append(cmd)
            self.envs.append(dict(env))
            return ns(0, _shuttle_stdout(_source_of(cwd)), "")
        return super().__call__(cmd, cwd, timeout, env)


def _oracle(runner, **kwargs):
    return RustOracle(terminal=TERMINAL, runner=runner, task_dir=FIXTURE,
                      shuttle_iterations=2, shuttle_depth=2, stress_runs=2,
                      **kwargs)


PROGRAM = f'fn main() {{ println!("{TERMINAL}"); }}\n'


def test_oracle_shuttle_wrong_schedule_fails_o3(tmp_path):
    source = PROGRAM + "// SHUTTLE_WRONG\n"
    result = _oracle(_MarkerRunner()).evaluate(source, tmp_path)
    assert result.layers["O2"].status == "pass"
    o3 = result.layers["O3"]
    assert (o3.status, o3.category) == ("fail", "wrong_output")
    assert o3.detail.startswith("schedule 3/4 (random): DONE t1=0 t2=1")
    assert o3.data["shuttle"]["output_check"] == "fail"
    assert result.functional_ok is False
    assert result.functional_ok_no_o4 is False
    first = next(name for name in ("O1", "O2", "O3", "O4")
                 if result.layers[name].status == "fail")
    assert first == "O3"
    tools = oracle_result_dict(result)["o3_tools"]
    assert tools["shuttle"] == {"status": "fail", "category": "wrong_output"}


def test_oracle_correct_schedules_pass(tmp_path):
    result = _oracle(_MarkerRunner()).evaluate(PROGRAM, tmp_path)
    shuttle = result.layers["O3"].data["shuttle"]
    assert result.layers["O3"].status == "pass"
    assert shuttle["output_check"] == "pass"
    assert shuttle["schedules_checked"] == 4


def test_codegen_mode_skips_the_output_check(tmp_path):
    source = PROGRAM + "// SHUTTLE_WRONG\n"
    result = _oracle(_MarkerRunner()).evaluate(source, tmp_path,
                                               check_terminal=False)
    o3 = result.layers["O3"]
    assert (o3.status, o3.category) == ("pass", None)
    assert o3.data["shuttle"]["output_check"] == "not_run"


def test_default_oracle_factory_passes_the_terminal(tmp_path):
    factory = cli.default_oracle_factory(timeout=30, runner=_MarkerRunner())
    oracle = factory(FIXTURE, TERMINAL)
    oracle.shuttle_iterations, oracle.stress_runs = 2, 1
    result = oracle.evaluate(PROGRAM + "// SHUTTLE_WRONG\n", tmp_path)
    assert result.layers["O3"].category == "wrong_output"


def _dynamic(tmp_path, replies):
    runner = _MarkerRunner()
    holder = {}

    def factory(spec, out):
        holder["client"] = _Client(replies)
        return holder["client"]

    out = tmp_path / "run"
    args = cli.build_parser().parse_args([
        "run", "--arm", "DYNAMIC", "--tasks", "lock-order/abba_2lock",
        "--reps", "1", "--rounds", "1", "--call-budget", "5",
        "--out", str(out), "--allow-missing-tools",
        "--budget-file", str(tmp_path / "budget.json"),
    ])
    rc = cli.cmd_run(args, client_factory=factory, oracle_runner=runner)
    cell = json.loads((out / "cells" / "lock-order" / "abba_2lock" / "0" /
                       "result.json").read_text(encoding="utf-8"))
    return rc, cell, holder["client"]


def test_dynamic_feedback_names_the_wrong_schedule(tmp_path):
    first = _rust(f'println!("{TERMINAL}");', "SHUTTLE_WRONG")
    second = _rust(f'println!("{TERMINAL}");')
    rc, cell, client = _dynamic(tmp_path, [first, second])
    assert rc == 0
    assert cell["accepted"] is True
    assert cell["baseline"]["accept_reason"] == "dynamic_pass"
    assert cell["rounds_used"] == 2
    feedback = client.users[1]
    assert "category: wrong_output" in feedback
    assert "schedule 3/" in feedback
    assert f"expected last line: {TERMINAL!r}" in feedback
    assert "observed last line: 'DONE t1=0 t2=1'" in feedback
    assert PCT_MARKER not in feedback and RANDOM_MARKER not in feedback
    assert str(tmp_path) not in feedback and "/Users/" not in feedback
    first_round = cell["baseline"]["rounds"][0]
    shuttle = first_round["tools"]["shuttle"]
    assert (shuttle["status"], shuttle["category"]) == ("fail", "wrong_output")


_LIVELOCK_STDERR = (
    "thread 'main' (99) panicked at /Users/someone/.cargo/registry/src/"
    "index.crates.io-1949cf8c6b5b557f/shuttle-0.8.1/src/runtime/execution.rs:203:17:\n"
    "exceeded max_steps bound 1000000. this might be caused by an unfair "
    "schedule (e.g., a spin loop)?\n"
    "failing schedule:\n\"\n" + "6ddbb6" * 2000 + "\n\"\n"
)


class _LivelockRunner(_MarkerRunner):
    def __call__(self, cmd, cwd, timeout, env):
        cmd = [str(part) for part in cmd]
        if Path(cmd[0]).name == "shuttle_probe":
            return ns(101, "", _LIVELOCK_STDERR)
        return super().__call__(cmd, cwd, timeout, env)


def test_dynamic_livelock_feedback_is_the_diagnostic_only(tmp_path):
    from skelnet.rusttools.dynamic_feedback import run_dynamic
    from skelnet.rusttools.runner import ToolRunner
    result = run_dynamic(ToolRunner(runner=_LivelockRunner()), tmp_path, PROGRAM,
                         terminal=TERMINAL, stress_runs=1, shuttle_iterations=2,
                         shuttle_depth=2, miri_seed_count=1)
    shuttle = next(s for s in result.slices if s.name == "shuttle")
    assert (shuttle.status, shuttle.category) == ("fail", "livelock")
    assert shuttle.blocking and not result.passed
    assert shuttle.text == ("## shuttle\ncategory: livelock\n"
                            "exceeded max_steps bound 1000000. this might be "
                            "caused by an unfair schedule (e.g., a spin loop)?")
    assert "6ddbb6" not in result.feedback
    assert "/Users/" not in result.feedback


def test_calibration_records_shuttle_counters(tmp_path):
    import argparse
    import shutil
    from skelnet.oracle_cli import cmd_calibrate
    fixtures = tmp_path / "fixtures"
    shutil.copytree(FIXTURE, fixtures / "abba_2lock")
    rust = fixtures / "abba_2lock" / "rust"
    for extra in rust.glob("*.rs"):
        if extra.name != "fixed.rs":
            extra.unlink()
    (rust / "expect.json").write_text(json.dumps({
        "schema_version": "skelnet-rust-expect-v1",
        "fixed.rs": {"functional": True}}), encoding="utf-8")
    (rust / "fixed.rs").write_text(PROGRAM + "// SHUTTLE_WRONG\n", encoding="utf-8")
    args = argparse.Namespace(layers="O1,O2,O3", fixtures=str(fixtures),
                              tasks="all", out=str(tmp_path / "out"),
                              mutants=False, report_only=True, timeout=30)
    assert cmd_calibrate(args, runner=_MarkerRunner()) == 0
    document = json.loads((tmp_path / "out" / "CALIBRATION.json").read_text())
    entry = document["tasks"][0]["programs"][0]
    assert entry["layers"]["O3"]["category"] == "wrong_output"
    assert entry["o3_shuttle"] == {
        "output_check": "fail", "schedules_checked": 4, "schedules_wrong": 1,
        "pct_completed": 2, "pct_abandoned": 1998, "random_completed": 2}
