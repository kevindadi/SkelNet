//! Reference program for condvar/bare_wait_no_predicate.
//!
//! Matches gold.skel: waiter and notifier share mutex `m` and condvar `cv`.
//! The flag `ready` lives in `m`. The waiter re-checks it after every wake,
//! so a signal that arrives first is not lost.
//!
//! Rewritten from the previous Arc<(Mutex, Condvar)> `pair` program, which
//! did not print the terminal line and did not use the entity names.

use std::sync::{Arc, Condvar, Mutex};
use std::thread;

fn waiter(m: Arc<Mutex<bool>>, cv: Arc<Condvar>) -> bool {
    let mut ready = m.lock().unwrap();
    while !*ready {
        ready = cv.wait(ready).unwrap();
    }
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
