//! Defect program for lock-order/cross_module_cycle (SkelNet R7a-2a).
//!
//! Source: ConcPlanVerify@8bf9fa49b0300e8be00fc5c0b61a98cd8d5aa53f
//! `benchmarks/families/lock-order/cross_module_cycle/rust/buggy.rs`.
//!
//! Changes: unnecessary imports dropped, `t2` moved into the `other` module and
//! both tasks written as named functions, bindings renamed to the contract
//! entities, and the computed terminal line added. The defect is unchanged:
//! `other::t2` takes the locks in the opposite order to `main::t1`.

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
        // DEFECT: opposite lock order across the module boundary.
        let mut gb = b.lock().unwrap();
        let ga = a.lock().unwrap();
        *gb += 1;
        let n = *gb;
        drop(ga);
        drop(gb);
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
