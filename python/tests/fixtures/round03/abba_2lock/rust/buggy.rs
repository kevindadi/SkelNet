//! Calibration fixture defect (round 3).
//!
//! Source: ConcPlanVerify commit 8bf9fa49b,
//! `benchmarks/families/lock-order/abba_2lock/rust/buggy.rs` (public repo).
//! Changes: binding names renamed to the contract entities (`a`, `b`, `t1`,
//! `t2`), the two spawn closures call named worker functions so the instrumenter
//! can label them, and the expected terminal line is printed after the joins.
//! The ABBA interleaving usually hangs O2 (the run watchdog fires) before O3's
//! Shuttle exploration deterministically reports the deadlock.
//! Expected defect: ABBA deadlock (t1 takes a->b, t2 takes b->a).

use std::sync::{Arc, Mutex};
use std::thread;

fn t1(a: Arc<Mutex<()>>, b: Arc<Mutex<()>>) {
    let ga = a.lock().unwrap();
    let gb = b.lock().unwrap();
    drop(gb);
    drop(ga);
}

fn t2(a: Arc<Mutex<()>>, b: Arc<Mutex<()>>) {
    let gb = b.lock().unwrap(); // opposite order
    let ga = a.lock().unwrap();
    drop(ga);
    drop(gb);
}

fn main() {
    let a = Arc::new(Mutex::new(()));
    let b = Arc::new(Mutex::new(()));

    let w1 = {
        let a = Arc::clone(&a);
        let b = Arc::clone(&b);
        thread::spawn(move || t1(a, b))
    };
    let w2 = {
        let a = Arc::clone(&a);
        let b = Arc::clone(&b);
        thread::spawn(move || t2(a, b))
    };

    w1.join().unwrap();
    w2.join().unwrap();
    println!("DONE t1=1 t2=1");
}
