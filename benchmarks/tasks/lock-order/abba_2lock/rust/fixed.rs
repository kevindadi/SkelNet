//! Reference Rust for lock-order/abba_2lock (SkelNet R7a-2a).
//!
//! Design: `gold.skel` has two workers `t1`, `t2` that both take the same two
//! locks `a` and `b` in a single global order. Each lock protects the count of
//! critical sections its owner ran; the workers return those counts so `main`
//! prints a computed terminal line.
//!
//! Rewritten from the ConcPlanVerify reference: the bindings are renamed to the
//! contract entities (`a`, `b`, `t1`, `t2`), the workers are named functions,
//! and the terminal line is computed instead of omitted.

use std::sync::{Arc, Mutex};
use std::thread;

fn t1(a: Arc<Mutex<u32>>, b: Arc<Mutex<u32>>) -> u32 {
    let mut ga = a.lock().unwrap();
    let gb = b.lock().unwrap();
    *ga += 1;
    let n = *ga;
    drop(gb);
    drop(ga);
    n
}

fn t2(a: Arc<Mutex<u32>>, b: Arc<Mutex<u32>>) -> u32 {
    let ga = a.lock().unwrap();
    let mut gb = b.lock().unwrap();
    *gb += 1;
    let n = *gb;
    drop(gb);
    drop(ga);
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
