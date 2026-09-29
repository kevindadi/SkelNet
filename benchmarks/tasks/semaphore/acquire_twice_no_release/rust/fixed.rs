//! Reference program for semaphore/acquire_twice_no_release.
//!
//! Matches gold.skel: one semaphore `s` starts with 1 permit. w1 does
//! take/post twice, w2 does take/post once. The printed counts are how many
//! of those pairs each worker finished.
//!
//! Rewritten from the hand-rolled Mutex+Condvar semaphore, which printed a
//! constant line and was not instrumented as `s`.

use concir_sync::Semaphore;
use std::sync::Arc;
use std::thread;

fn w1(s: Arc<Semaphore>) -> u32 {
    let mut turns = 0u32;
    s.take();
    s.post();
    turns += 1;
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
