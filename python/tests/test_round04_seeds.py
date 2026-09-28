"""T0/T1: Shuttle seed wiring and the feedback window."""

from pathlib import Path

from skelnet.oracle import SHUTTLE_SHIM_CRATE
from skelnet.rusttools.runner import ToolRunner, default_runner
from skelnet.rusttools.seeds import (FEEDBACK_MIRI_SEED_COUNT,
                                     FEEDBACK_MIRI_SEED_DEFAULT_COUNT,
                                     FEEDBACK_MIRI_SEED_START,
                                     FEEDBACK_SHUTTLE_SEED, ORACLE_MIRI_SEED_START,
                                     ORACLE_SHUTTLE_SEED, feedback_miri_window,
                                     feedback_shuttle_seed)
from skelnet.rusttools.shuttle import evaluate_shuttle

from round03_helpers import ns, rust_tools

_ABBA = """\
use std::sync::{Arc, Mutex};
use std::thread;
fn main() {
    let a = Arc::new(Mutex::new(()));
    let b = Arc::new(Mutex::new(()));
    let a1 = Arc::clone(&a);
    let b1 = Arc::clone(&b);
    let t1 = thread::spawn(move || {
        let _ga = a1.lock().unwrap();
        let _gb = b1.lock().unwrap();
    });
    let a2 = Arc::clone(&a);
    let b2 = Arc::clone(&b);
    let t2 = thread::spawn(move || {
        let _gb = b2.lock().unwrap();
        let _ga = a2.lock().unwrap();
    });
    t1.join().unwrap();
    t2.join().unwrap();
}
"""


def test_feedback_miri_window_is_inside_the_reserved_range():
    start, count = feedback_miri_window()
    assert count == FEEDBACK_MIRI_SEED_DEFAULT_COUNT == 16
    assert start == FEEDBACK_MIRI_SEED_START
    used = range(start, start + count)
    assert start + count <= FEEDBACK_MIRI_SEED_START + FEEDBACK_MIRI_SEED_COUNT
    oracle = range(ORACLE_MIRI_SEED_START, ORACLE_MIRI_SEED_START + 16)
    assert set(used).isdisjoint(oracle)
    assert feedback_shuttle_seed() == FEEDBACK_SHUTTLE_SEED
    assert feedback_shuttle_seed() != ORACLE_SHUTTLE_SEED


def test_evaluate_shuttle_puts_the_requested_seed_in_the_environment(tmp_path):
    seen = []

    def run(cmd, cwd, timeout, env):
        seen.append(dict(env))
        if "build" in cmd:
            return ns(0, "", "")
        return ns(1, "", "deadlock! blocked tasks: [main]\n")

    tools = ToolRunner(runner=run, toolchain="nightly-test")
    evaluate_shuttle(tools, tmp_path / "oracle", "fn main() {}",
                     shim_path=tmp_path, seed=ORACLE_SHUTTLE_SEED, timeout=5)
    evaluate_shuttle(tools, tmp_path / "feedback", "fn main() {}",
                     shim_path=tmp_path, seed=feedback_shuttle_seed(), timeout=5)
    seeds = [env.get("SHUTTLE_RANDOM_SEED") for env in seen
             if "SHUTTLE_RANDOM_SEED" in env]
    assert seeds == [str(ORACLE_SHUTTLE_SEED), str(FEEDBACK_SHUTTLE_SEED)]


@rust_tools
def test_same_shuttle_seed_replays_the_same_failing_schedule(tmp_path):
    """SHUTTLE_RANDOM_SEED is read by Shuttle 0.8.1 check_pct / check_random."""
    def once(dest: Path, seed: int):
        calls = []

        def run(cmd, cwd, timeout, env):
            calls.append(dict(env))
            return default_runner(cmd, cwd, timeout, env)

        result = evaluate_shuttle(
            ToolRunner(runner=run), dest, _ABBA, shim_path=SHUTTLE_SHIM_CRATE,
            iterations=300, depth=3, seed=seed, timeout=240)
        planted = [env.get("SHUTTLE_RANDOM_SEED") for env in calls
                   if env.get("SHUTTLE_RANDOM_SEED")]
        return result, planted

    first, seeds_a = once(tmp_path / "a", FEEDBACK_SHUTTLE_SEED)
    second, seeds_b = once(tmp_path / "b", FEEDBACK_SHUTTLE_SEED)
    assert first.category == "deadlock"
    assert first.data.get("schedule")
    assert first.data.get("schedule") == second.data.get("schedule")
    assert seeds_a == seeds_b == [str(FEEDBACK_SHUTTLE_SEED)]
    other, seeds_c = once(tmp_path / "c", ORACLE_SHUTTLE_SEED)
    assert seeds_c == [str(ORACLE_SHUTTLE_SEED)]
    assert other.category == "deadlock"
