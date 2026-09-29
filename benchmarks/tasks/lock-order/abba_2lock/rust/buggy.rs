//! Defect program for lock-order/abba_2lock (SkelNet R7a-2a).
//!
//! Source: ConcPlanVerify@8bf9fa49b0300e8be00fc5c0b61a98cd8d5aa53f
//! `benchmarks/families/lock-order/abba_2lock/rust/buggy.rs`.
//!
//! Changes: bindings renamed to the contract entities (`a`, `b`, `t1`, `t2`),
//! the workers are named functions, and the computed terminal line is added.
//! The defect is unchanged: `t2` takes the locks in the opposite order, so the
//! two workers can each hold one lock and wait forever for the other.

use std::sync::{Arc, Mutex};
use std::thread;

fn t1(a: Arc<Mutex<u32>>, b: Arc<Mutex<u32>>) -> u32 {
    let mut ga = a.lock().unwrap();
    *ga += 1;
    let n = *ga;
    let gb = b.lock().unwrap();
    let _ = &*gb;
    drop(gb);
    drop(ga);
    n
}

fn t2(a: Arc<Mutex<u32>>, b: Arc<Mutex<u32>>) -> u32 {
    // DEFECT: opposite lock order.
    let mut gb = b.lock().unwrap();
    *gb += 1;
    let n = *gb;
    let ga = a.lock().unwrap();
    let _ = &*ga;
    drop(ga);
    drop(gb);
    n
}

fn main() {
    let a = Arc::new(Mutex::new(0u32));
    let b = Arc::new(Mutex::new(0u32));

    let (a1, b1) = (Arc::clone(&a), Arc::clone(&b));
    let t1 = thread::spawn(move || t1(a1, b1));
    let (a2, b2) = (Arc::clone(&a), Arc::clone(&b));
    let t2 = thread::spawn(move || t2(a2, b2));

    let r1 = t1.join().unwrap();
    let r2 = t2.join().unwrap();
    println!("DONE t1={} t2={}", r1, r2);
}
