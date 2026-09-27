//! Reference Rust for tests/e2e/signal_loss/fixed.json.
//! Fix: the waiter re-checks the protected `ready` flag in a loop, so a
//! notification that arrives before the wait can never be lost.

use std::sync::{Arc, Condvar, Mutex};
use std::thread;

fn main() {
    let pair = Arc::new((Mutex::new(false), Condvar::new()));

    let pair_w = Arc::clone(&pair);
    let waiter = thread::spawn(move || {
        let (mtx, cv) = &*pair_w;
        let mut ready = mtx.lock().unwrap(); // s1: lock mtx
        while !*ready {
            // s2: read ready, branch; s3: wait, loop back to s2
            ready = cv.wait(ready).unwrap();
        }
        drop(ready); // s4: drop mtx
    });

    let pair_n = Arc::clone(&pair);
    let notifier = thread::spawn(move || {
        let (mtx, cv) = &*pair_n;
        let mut ready = mtx.lock().unwrap(); // s1: lock mtx
        *ready = true; // s2: write ready = true
        cv.notify_all(); // s3: notify_all
        drop(ready); // s4: drop mtx
    });

    waiter.join().unwrap();
    notifier.join().unwrap();
}
