//! Reference Rust for lock-order/cycle_3lock (SkelNet R7a-2a).
//!
//! Design: `gold.skel` has workers `t1` (a, b), `t2` (b, c) and `t3` (a, c).
//! Every worker takes its two locks in the global order a < b < c, so no
//! circular wait can form. Each lock protects the completion count of the
//! worker that owns it; the workers return those counts.
//!
//! Rewritten from the ConcPlanVerify reference (whose bindings were
//! `mtx_a`/`mtx_b`/`mtx_c` and `w1`/`w2`/`w3`): renamed to the contract
//! entities `a`/`b`/`c` and `t1`/`t2`/`t3`, restructured as named worker
//! functions, and given a computed terminal line.

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

fn t2(b: Arc<Mutex<u32>>, c: Arc<Mutex<u32>>) -> u32 {
    let mut gb = b.lock().unwrap();
    let gc = c.lock().unwrap();
    *gb += 1;
    let n = *gb;
    drop(gc);
    drop(gb);
    n
}

fn t3(a: Arc<Mutex<u32>>, c: Arc<Mutex<u32>>) -> u32 {
    let ga = a.lock().unwrap();
    let mut gc = c.lock().unwrap();
    *gc += 1;
    let n = *gc;
    drop(gc);
    drop(ga);
    n
}

fn main() {
    let a = Arc::new(Mutex::new(0u32));
    let b = Arc::new(Mutex::new(0u32));
    let c = Arc::new(Mutex::new(0u32));

    let (a1, b1) = (Arc::clone(&a), Arc::clone(&b));
    let t1 = thread::spawn(move || t1(a1, b1));
    let (b2, c2) = (Arc::clone(&b), Arc::clone(&c));
    let t2 = thread::spawn(move || t2(b2, c2));
    let (a3, c3) = (Arc::clone(&a), Arc::clone(&c));
    let t3 = thread::spawn(move || t3(a3, c3));

    let r1 = t1.join().unwrap();
    let r2 = t2.join().unwrap();
    let r3 = t3.join().unwrap();
    println!("DONE t1={} t2={} t3={}", r1, r2, r3);
}
