//! Reference Rust for lock-order/cross_module_cycle (SkelNet R7a-2a).
//!
//! Design: `gold.skel` splits the protocol over two modules. Module `main`
//! owns lock `a` and task `t1`; module `other` owns lock `b` and task `t2`.
//! Both tasks take `a` then `b`, so every schedule terminates. Each lock
//! protects its owner task's completion count, which `main` prints.
//!
//! Both locks are constructed in `main` (the instrumenter names resources from
//! the `let` bindings there); the `other` module contains only `t2`.
//!
//! Rewritten from the ConcPlanVerify reference: bindings renamed to the
//! contract entities, `t2` moved into `other` and both tasks written as named
//! functions, and the terminal line computed.

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

mod other {
    use std::sync::{Arc, Mutex};

    pub fn t2(a: Arc<Mutex<u32>>, b: Arc<Mutex<u32>>) -> u32 {
        let ga = a.lock().unwrap();
        let mut gb = b.lock().unwrap();
        *gb += 1;
        let n = *gb;
        drop(gb);
        drop(ga);
        n
    }
}

fn main() {
    let a = Arc::new(Mutex::new(0u32));
    let b = Arc::new(Mutex::new(0u32));

    let (a1, b1) = (Arc::clone(&a), Arc::clone(&b));
    let t1 = thread::spawn(move || t1(a1, b1));
    let (a2, b2) = (Arc::clone(&a), Arc::clone(&b));
    let t2 = thread::spawn(move || other::t2(a2, b2));

    let r1 = t1.join().unwrap();
    let r2 = t2.join().unwrap();
    println!("DONE t1={} t2={}", r1, r2);
}
