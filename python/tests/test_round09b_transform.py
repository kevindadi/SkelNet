"""B1: the generated Shuttle main (PCT step bound, schedule markers)."""

import subprocess

from skelnet.oracle import SHUTTLE_SHIM_CRATE
from skelnet.rusttools.shuttle import (PCT_MARKER, RANDOM_MARKER, transform_source,
                                       write_shuttle_project)

from round03_helpers import rust_tools

SAMPLE = """use std::sync::{Arc, Mutex};
use std::thread;

fn main() {
    let m = Arc::new(Mutex::new(()));
    let h = thread::spawn(move || { let _ = m.lock(); });
    h.join().unwrap();
}
"""

BODY = """use shuttle::sync::{Arc, Mutex};
use shuttle::thread;

fn __skelnet_body() {
    let m = Arc::new(Mutex::new(()));
    let h = thread::spawn(move || { let _ = m.lock(); });
    h.join().unwrap();
}
"""

EXPECTED_PLAIN = BODY + """
fn main() {
    let mut __skelnet_pct_config = shuttle::Config::new();
    __skelnet_pct_config.max_steps = shuttle::MaxSteps::ContinueAfter(10000);
    shuttle::Runner::new(
        shuttle::scheduler::PctScheduler::new(3, 2000),
        __skelnet_pct_config,
    ).run(|| { __skelnet_body(); });
    shuttle::check_random(|| { __skelnet_body(); }, 2000);
}
"""

EXPECTED_MARKERS = BODY + """
fn main() {
    let mut __skelnet_pct_config = shuttle::Config::new();
    __skelnet_pct_config.max_steps = shuttle::MaxSteps::ContinueAfter(10000);
    shuttle::Runner::new(
        shuttle::scheduler::PctScheduler::new(3, 2000),
        __skelnet_pct_config,
    ).run(|| { __skelnet_body(); println!("\\n__SKELNET_SHUTTLE_END_PCT__"); });
    shuttle::check_random(|| { __skelnet_body(); println!("\\n__SKELNET_SHUTTLE_END_RANDOM__"); }, 2000);
}
"""


def test_plain_snapshot():
    transformed, reason = transform_source(SAMPLE)
    assert reason is None
    assert transformed == EXPECTED_PLAIN


def test_marker_snapshot():
    transformed, reason = transform_source(SAMPLE, markers=True)
    assert reason is None
    assert transformed == EXPECTED_MARKERS


def test_iterations_and_depth_reach_both_schedulers():
    transformed, _ = transform_source(SAMPLE, iterations=7, depth=2, markers=True)
    assert "PctScheduler::new(2, 7)" in transformed
    assert f'println!("\\n{RANDOM_MARKER}"); }}, 7);' in transformed
    assert "shuttle::check_pct" not in transformed


@rust_tools
def test_marker_main_builds_and_prints_one_marker_per_schedule(tmp_path):
    transformed, _ = transform_source(SAMPLE, iterations=3, depth=2, markers=True)
    binary = write_shuttle_project(tmp_path, transformed, SHUTTLE_SHIM_CRATE)
    build = subprocess.run(["cargo", "build", "--offline", "-q"], cwd=tmp_path,
                           capture_output=True, text=True, timeout=600)
    assert build.returncode == 0, build.stderr[-2000:]
    run = subprocess.run([str(binary)], cwd=tmp_path, capture_output=True,
                         text=True, timeout=120,
                         env={"SHUTTLE_RANDOM_SEED": "1", "PATH": "/usr/bin:/bin"})
    assert run.returncode == 0, run.stderr[-2000:]
    lines = run.stdout.splitlines()
    assert lines.count(PCT_MARKER) == 3
    assert lines.count(RANDOM_MARKER) == 3
