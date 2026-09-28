//! Defect program for condvar/bare_wait_no_predicate.
//!
//! Source: ConcPlanVerify@8bf9fa49b0300e8be00fc5c0b61a98cd8d5aa53f:benchmarks/families/condvar/bare_wait_no_predicate/rust/buggy.rs
//! The defect is unchanged: the waiter calls wait() without looking at the
//! flag, so a signal that already happened is lost and the waiter blocks.
//! Adapted only to bind `m` and `cv` separately, use the role names, and
//! print the flag the waiter observed.

use std::sync::{Arc, Condvar, Mutex};
use std::thread;

fn waiter(m: Arc<Mutex<bool>>, cv: Arc<Condvar>) -> bool {
    let ready = m.lock().unwrap();
    // Wait without checking the flag first. A signal that already happened is lost.
    let ready = cv.wait(ready).unwrap();
    *ready
}

fn notifier(m: Arc<Mutex<bool>>, cv: Arc<Condvar>) {
    let mut ready = m.lock().unwrap();
    *ready = true;
    cv.notify_one();
}

fn main() {
    let m = Arc::new(Mutex::new(false));
    let cv = Arc::new(Condvar::new());
    let (m_w, cv_w) = (Arc::clone(&m), Arc::clone(&cv));
    let waiter = thread::spawn(move || waiter(m_w, cv_w));
    let (m_n, cv_n) = (Arc::clone(&m), Arc::clone(&cv));
    let notifier = thread::spawn(move || notifier(m_n, cv_n));
    let ready = waiter.join().unwrap();
    notifier.join().unwrap();
    println!("DONE ready={}", ready);
}
