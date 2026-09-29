"""T4: snapshot the textual std -> Shuttle rewrite."""

from skelnet.rusttools.shuttle import transform_source

SAMPLE = """use std::sync::{Arc, Mutex};
use std::thread;

fn main() {
    let m = Arc::new(Mutex::new(()));
    let h = thread::spawn(move || { let _ = m.lock(); });
    h.join().unwrap();
}
"""

EXPECTED = """use shuttle::sync::{Arc, Mutex};
use shuttle::thread;

fn __skelnet_body() {
    let m = Arc::new(Mutex::new(()));
    let h = thread::spawn(move || { let _ = m.lock(); });
    h.join().unwrap();
}

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


def test_transform_snapshot():
    transformed, reason = transform_source(SAMPLE)
    assert reason is None
    assert transformed == EXPECTED


def test_scope_is_unsupported():
    transformed, reason = transform_source("fn main() { std::thread::scope(|s| {}); }\n")
    assert transformed is None
    assert reason == "thread::scope"


def test_once_lock_is_unsupported():
    transformed, reason = transform_source("use std::sync::OnceLock;\nfn main() {}\n")
    assert transformed is None
    assert reason == "OnceLock"


def test_main_returning_value_is_unsupported():
    transformed, reason = transform_source("fn main() -> Result<(), ()> { Ok(()) }\n")
    assert transformed is None
    assert reason == "`fn main` returns a value"
