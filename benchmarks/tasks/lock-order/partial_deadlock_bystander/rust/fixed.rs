//! Reference Rust for tests/e2e/partial_deadlock/fixed.json.
//! Fix: the semaphore cross-handshake is removed and both workers take the
//! mutexes in the same global order (a then b), so both reach return.

use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

fn main() {
    let mtx_a = Arc::new(Mutex::new(()));
    let mtx_b = Arc::new(Mutex::new(()));

    let (ma, mb) = (Arc::clone(&mtx_a), Arc::clone(&mtx_b));
    let worker_a = thread::spawn(move || {
        let ga = ma.lock().unwrap(); // s1: lock mtx_a
        let gb = mb.lock().unwrap(); // s2: lock mtx_b
        drop(gb); // s3
        drop(ga); // s4
    });

    let (ma2, mb2) = (Arc::clone(&mtx_a), Arc::clone(&mtx_b));
    let worker_b = thread::spawn(move || {
        let ga = ma2.lock().unwrap(); // s1: lock mtx_a (same order)
        let gb = mb2.lock().unwrap(); // s2: lock mtx_b
        drop(gb); // s3
        drop(ga); // s4
    });

    // Detached bystander keeps looping; main never joins it.
    thread::spawn(move || loop {
        thread::sleep(Duration::from_millis(10)); // s1/s2: nop loop
    });

    // Goals: worker_a.ret and worker_b.ret are both reachable.
    worker_a.join().unwrap();
    worker_b.join().unwrap();
}
