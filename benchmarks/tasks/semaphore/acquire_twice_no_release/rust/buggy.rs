//! Defect program for semaphore/acquire_twice_no_release.
//!
//! Source: ConcPlanVerify@8bf9fa49b0300e8be00fc5c0b61a98cd8d5aa53f:benchmarks/families/semaphore/acquire_twice_no_release/rust/buggy.rs
//! The defect is unchanged: w1 takes the only permit twice before posting
//! once, so it blocks forever on the second take and w2 cannot proceed.
//! Adapted to `concir_sync::Semaphore` named `s`, role functions, and the
//! same completion-count print as fixed.rs.

use concir_sync::Semaphore;
use std::sync::Arc;
use std::thread;

fn w1(s: Arc<Semaphore>) -> u32 {
    let mut turns = 0u32;
    s.take();
    s.take();
    s.post();
    turns += 1;
    turns
}

fn w2(s: Arc<Semaphore>) -> u32 {
    let mut turns = 0u32;
    s.take();
    s.post();
    turns += 1;
    turns
}

fn main() {
    let s = Semaphore::new(1);
    let s1 = Arc::clone(&s);
    let w1 = thread::spawn(move || w1(s1));
    let s2 = Arc::clone(&s);
    let w2 = thread::spawn(move || w2(s2));
    let n1 = w1.join().unwrap();
    let n2 = w2.join().unwrap();
    println!("DONE w1={} w2={}", n1, n2);
}
