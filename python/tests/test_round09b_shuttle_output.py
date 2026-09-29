"""B2: per-schedule terminal check and step-bound classification.

The fake runner answers from the generated project source: it only prints
schedule markers when ``src/main.rs`` really contains them, so these tests
fail if ``evaluate_shuttle`` stops asking ``transform_source`` for markers.
"""

import subprocess
from pathlib import Path

from skelnet.rusttools.runner import ToolRunner
from skelnet.rusttools.shuttle import PCT_MARKER, RANDOM_MARKER, evaluate_shuttle

from round03_helpers import ns

SRC = "fn main() { std::thread::spawn(|| {}).join().unwrap(); }\n"
TERMINAL = "DONE c=2"
ITERATIONS = 4

MAX_STEPS_STDERR = (
    "thread 'main' (4242) panicked at /Users/someone/.cargo/registry/src/"
    "index.crates.io-1949cf8c6b5b557f/shuttle-0.8.1/src/runtime/execution.rs:203:17:\n"
    "exceeded max_steps bound 1000000. this might be caused by an unfair "
    "schedule (e.g., a spin loop)?\n"
    "failing schedule:\n\"\n9102c0843d8180b4f7\n\"\n"
    "pass that string to `shuttle::replay` to replay the failure\n"
)


def schedule_output(lines_by_schedule, *, pct=ITERATIONS, trailing=""):
    """stdout for ``pct`` PCT then the remaining random schedules."""
    out = []
    for index, lines in enumerate(lines_by_schedule):
        marker = PCT_MARKER if index < pct else RANDOM_MARKER
        out.extend(lines)
        out.append("")
        out.append(marker)
    return "\n".join(out) + "\n" + trailing


def good(n=2 * ITERATIONS):
    return [["working", TERMINAL] for _ in range(n)]


class FakeShuttle:
    """Build succeeds; the Shuttle binary returns ``stdout``/``stderr``/``rc``
    only when the project was generated with markers."""

    def __init__(self, stdout="", stderr="", rc=0, timeout=False):
        self.stdout, self.stderr, self.rc, self.timeout = stdout, stderr, rc, timeout
        self.sources: list[str] = []

    def __call__(self, cmd, cwd, timeout, env):
        cwd = Path(cwd)
        if "build" in cmd:
            return ns(0, "", "")
        source = (cwd / "src" / "main.rs").read_text(encoding="utf-8")
        self.sources.append(source)
        if self.timeout:
            raise subprocess.TimeoutExpired(cmd, timeout)
        if PCT_MARKER not in source or RANDOM_MARKER not in source:
            return ns(0, "", "")
        return ns(self.rc, self.stdout, self.stderr)


def evaluate(tmp_path, fake, terminal=TERMINAL):
    return evaluate_shuttle(ToolRunner(runner=fake, toolchain=None), tmp_path, SRC,
                            shim_path=tmp_path / "shim", iterations=ITERATIONS,
                            depth=2, terminal=terminal)


def test_all_schedules_correct_passes_with_counts(tmp_path):
    result = evaluate(tmp_path, FakeShuttle(schedule_output(good())))
    assert (result.status, result.category) == ("pass", None)
    assert result.data["output_check"] == "pass"
    assert result.data["schedules_checked"] == 2 * ITERATIONS
    assert result.data["schedules_wrong"] == 0
    assert result.data["pct_completed"] == ITERATIONS
    assert result.data["random_completed"] == ITERATIONS
    assert result.data["pct_abandoned"] == 0


def test_wrong_pct_schedule_is_wrong_output(tmp_path):
    lines = good()
    lines[1] = ["working", "DONE c=1"]
    result = evaluate(tmp_path, FakeShuttle(schedule_output(lines)))
    assert (result.status, result.category) == ("fail", "wrong_output")
    assert result.detail == f"schedule 2/{2 * ITERATIONS} (pct): DONE c=1"
    assert result.data["first_wrong"] == {"index": 2, "scheduler": "pct",
                                          "line": "DONE c=1"}
    assert result.data["schedules_wrong"] == 1
    assert result.data["output_check"] == "fail"
    assert result.data["schedule"] is None


def test_wrong_random_schedule_is_wrong_output(tmp_path):
    lines = good()
    lines[6] = ["DONE c=1"]
    lines[7] = ["DONE c=0"]
    result = evaluate(tmp_path, FakeShuttle(schedule_output(lines)))
    assert result.category == "wrong_output"
    assert result.detail == f"schedule 7/{2 * ITERATIONS} (random): DONE c=1"
    assert result.data["first_wrong"]["scheduler"] == "random"
    assert result.data["schedules_wrong"] == 2


def test_empty_schedule_output_is_wrong(tmp_path):
    lines = good()
    lines[0] = []
    result = evaluate(tmp_path, FakeShuttle(schedule_output(lines)))
    assert result.category == "wrong_output"
    assert result.detail.endswith("(pct): (no non-empty stdout line)")
    assert result.data["first_wrong"]["line"] == ""


def test_trailing_space_is_not_stripped(tmp_path):
    lines = good()
    lines[3] = [TERMINAL + " "]
    result = evaluate(tmp_path, FakeShuttle(schedule_output(lines)))
    assert result.category == "wrong_output"


def test_abandoned_pct_iterations_are_counted(tmp_path):
    lines = good(ITERATIONS - 1 + ITERATIONS)
    result = evaluate(tmp_path, FakeShuttle(schedule_output(lines, pct=ITERATIONS - 1)))
    assert result.status == "pass"
    assert result.data["pct_completed"] == ITERATIONS - 1
    assert result.data["random_completed"] == ITERATIONS
    assert result.data["pct_abandoned"] == 1


def test_residue_after_last_marker_is_not_a_schedule(tmp_path):
    stdout = schedule_output(good(), trailing="DONE c=1\n")
    result = evaluate(tmp_path, FakeShuttle(stdout))
    assert result.status == "pass"
    assert result.data["schedules_checked"] == 2 * ITERATIONS


def test_print_without_newline_still_splits(tmp_path):
    # The program ends with `print!` (no newline): the marker's leading "\n"
    # still puts the marker on its own line.
    stdout = "".join(f"working\n{TERMINAL}\n{PCT_MARKER}\n" for _ in range(ITERATIONS))
    stdout += "".join(f"{TERMINAL}\n{RANDOM_MARKER}\n" for _ in range(ITERATIONS))
    result = evaluate(tmp_path, FakeShuttle(stdout))
    assert result.data["output_check"] == "pass"
    assert result.data["schedules_checked"] == 2 * ITERATIONS
    bad = f"DONE c=1\n{PCT_MARKER}\n" + stdout
    assert evaluate(tmp_path, FakeShuttle(bad)).category == "wrong_output"


def test_no_concurrency_checks_the_single_schedule(tmp_path):
    stderr = "thread 'main' panicked at x:\ntest closure did not exercise any concurrency\n"
    wrong = evaluate(tmp_path, FakeShuttle(f"DONE c=1\n\n{PCT_MARKER}\n", stderr, 101))
    assert (wrong.status, wrong.category) == ("fail", "wrong_output")
    assert wrong.data["no_concurrency"] is True
    assert wrong.data["pct_abandoned"] is None
    right = evaluate(tmp_path, FakeShuttle(f"{TERMINAL}\n\n{PCT_MARKER}\n", stderr, 101))
    assert (right.status, right.category) == ("pass", None)
    assert right.detail == "no concurrency to explore"
    assert right.data["no_concurrency"] is True
    assert right.data["output_check"] == "pass"


def test_deadlock_wins_over_earlier_wrong_schedules(tmp_path):
    lines = [["DONE c=1"], ["working", TERMINAL]]
    stdout = schedule_output(lines, pct=2)
    fake = FakeShuttle(stdout, "deadlock! blocked tasks: [main, t1]\n", 1)
    result = evaluate(tmp_path, fake)
    assert (result.status, result.category) == ("fail", "deadlock")
    assert result.data["schedules_wrong"] == 1
    assert result.data["schedules_checked"] == 2
    assert result.data["pct_abandoned"] is None


def test_random_step_bound_is_livelock(tmp_path):
    fake = FakeShuttle(schedule_output(good(ITERATIONS)), MAX_STEPS_STDERR, 101)
    result = evaluate(tmp_path, fake)
    assert (result.status, result.category) == ("fail", "livelock")
    assert result.detail.startswith("exceeded max_steps bound 1000000")
    assert "/" not in result.detail
    assert result.data["schedule"] == "9102c0843d8180b4f7"


def test_deadlock_wins_over_step_bound(tmp_path):
    fake = FakeShuttle("", "deadlock! blocked tasks: [main]\n" + MAX_STEPS_STDERR, 1)
    assert evaluate(tmp_path, fake).category == "deadlock"


def test_other_panic_stays_panic(tmp_path):
    fake = FakeShuttle("", "thread 'main' panicked at src/main.rs:3:5:\nboom\n", 101)
    result = evaluate(tmp_path, fake)
    assert (result.status, result.category) == ("fail", "panic")


def test_timeout_stays_deadlock(tmp_path):
    result = evaluate(tmp_path, FakeShuttle(timeout=True))
    assert (result.status, result.category) == ("fail", "deadlock")


def test_no_markers_is_no_schedules_pass(tmp_path):
    result = evaluate(tmp_path, FakeShuttle("DONE c=1\n"))
    assert result.status == "pass"
    assert result.data["output_check"] == "no_schedules"


def test_no_terminal_skips_the_output_check(tmp_path):
    lines = [["anything at all"] for _ in range(2 * ITERATIONS)]
    result = evaluate(tmp_path, FakeShuttle(schedule_output(lines)), terminal=None)
    assert result.status == "pass"
    assert result.data["output_check"] == "not_run"


def test_output_mismatch_failure_file(tmp_path):
    lines = good()
    lines[4] = [f"line {i}" for i in range(60)] + ["DONE c=1"]
    evaluate(tmp_path, FakeShuttle(schedule_output(lines)))
    text = (tmp_path / "shuttle" / "failure.txt").read_text(encoding="utf-8")
    body = text.splitlines()
    assert body[0] == f"output mismatch in schedule 5/{2 * ITERATIONS} (random)"
    assert body[1] == "expected last line: 'DONE c=2'"
    assert body[2] == "observed last line: 'DONE c=1'"
    assert body[3] == "output of that schedule (first 40 lines):"
    assert body[4:] == [f"line {i}" for i in range(40)]
    assert str(tmp_path) not in text and "/Users/" not in text
    assert PCT_MARKER not in text and RANDOM_MARKER not in text


def test_failure_file_has_no_markers(tmp_path):
    lines = [["working", TERMINAL]]
    fake = FakeShuttle(schedule_output(lines, pct=1),
                       "thread 'main' panicked at src/main.rs:3:5:\nboom\n", 101)
    evaluate(tmp_path, fake)
    text = (tmp_path / "shuttle" / "failure.txt").read_text(encoding="utf-8")
    assert "boom" in text and TERMINAL in text
    assert PCT_MARKER not in text and RANDOM_MARKER not in text


def test_program_printing_panic_words_still_passes(tmp_path):
    lines = [["deadlock! blocked tasks", "panicked at", TERMINAL]
             for _ in range(2 * ITERATIONS)]
    result = evaluate(tmp_path, FakeShuttle(schedule_output(lines)))
    assert (result.status, result.category) == ("pass", None)
