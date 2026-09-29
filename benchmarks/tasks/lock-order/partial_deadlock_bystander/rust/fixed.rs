//! Reference Rust for lock-order/partial_deadlock_bystander (SkelNet R7a-2a).
//!
//! Design: `gold.skel` has two short-lived workers `a` and `b` that each take
//! both locks `a` and `b` (in the same order), plus an independent `bystander`
//! that waits until `flag` is set. The semaphores `sa`/`sb` are declared but
//! never used by the gold design (`defect_family: goal_layer`), so the
//! reference does not construct them. `flag` is a shared atomic variable.
//!
//! The role names `a`/`b` clash with the lock names, so the two locks are built
//! as fields of a struct literal (the instrumenter names them by field).
//!
//! Rewritten from the ConcPlanVerify reference: bindings renamed to the
//! contract entities, `thread::sleep` removed, the bystander joined after
//! `flag` is set, and the terminal line computed. The bystander parks on the
//! atomic instead of spin-looping: a tight spin exceeds Shuttle's bounded
//! `max_steps` (the design is unchanged, only the waiting primitive differs).

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;

struct Locks {
    a: Mutex<u32>,
    b: Mutex<u32>,
}

fn a(locks: Arc<Locks>) -> u32 {
    let mut ga = locks.a.lock().unwrap();
    *ga += 1;
    let n = *ga;
    let gb = locks.b.lock().unwrap();
    let _ = &*gb;
    drop(gb);
    drop(ga);
    n
}

fn b(locks: Arc<Locks>) -> u32 {
    let ga = locks.a.lock().unwrap();
    let mut gb = locks.b.lock().unwrap();
    *gb += 1;
    let n = *gb;
    drop(gb);
    drop(ga);
    n
}

fn bystander(flag: Arc<AtomicBool>) {
    while !flag.load(Ordering::SeqCst) {
        thread::park();
    }
}

fn main() {
    let locks = Arc::new(Locks {
        a: Mutex::new(0u32),
        b: Mutex::new(0u32),
    });
    let flag = Arc::new(AtomicBool::new(false));

    let (l1, l2) = (Arc::clone(&locks), Arc::clone(&locks));
    let a = thread::spawn(move || a(l1));
    let b = thread::spawn(move || b(l2));
    let f = Arc::clone(&flag);
    let bystander = thread::spawn(move || bystander(f));

    let ra = a.join().unwrap();
    let rb = b.join().unwrap();
    flag.store(true, Ordering::SeqCst);
    bystander.thread().unpark();
    bystander.join().unwrap();

    println!("DONE a={} b={}", ra, rb);
}
