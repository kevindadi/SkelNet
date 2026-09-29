//! Defect program for lock-order/cycle_3lock (SkelNet R7a-2a).
//!
//! Source: ConcPlanVerify@8bf9fa49b0300e8be00fc5c0b61a98cd8d5aa53f
//! `benchmarks/families/lock-order/cycle_3lock/rust/buggy.rs`.
//!
//! Changes: bindings renamed to the contract entities, the workers are named
//! functions, and the computed terminal line is added. The defect is unchanged:
//! `t1` takes a->b, `t2` takes b->c and `t3` takes c->a, forming a circular
//! wait, so all three can hold one lock and wait forever for the next.

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

fn t2(b: Arc<Mutex<u32>>, c: Arc<Mutex<u32>>) -> u32 {
    let mut gb = b.lock().unwrap();
    *gb += 1;
    let n = *gb;
    let gc = c.lock().unwrap();
    let _ = &*gc;
    drop(gc);
    drop(gb);
    n
}

fn t3(a: Arc<Mutex<u32>>, c: Arc<Mutex<u32>>) -> u32 {
    // DEFECT: t3 takes c then a, closing the cycle a -> b -> c -> a.
    let mut gc = c.lock().unwrap();
    *gc += 1;
    let n = *gc;
    let ga = a.lock().unwrap();
    let _ = &*ga;
    drop(ga);
    drop(gc);
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
