//! Defect program for lock-order/partial_deadlock_bystander (SkelNet R7a-2a).
//!
//! Source: ConcPlanVerify@8bf9fa49b0300e8be00fc5c0b61a98cd8d5aa53f
//! `benchmarks/families/lock-order/partial_deadlock_bystander/rust/buggy.rs`.
//!
//! Changes: bindings renamed to the contract entities, the hand-written
//! semaphore replaced by `concir_sync::Semaphore` (matching the gold's declared
//! `sa`/`sb`), the bystander's `thread::sleep` removed (it now busy-waits on
//! `flag` like the gold loop), and the computed terminal line added. The defect
//! is unchanged: the two workers release their own permit and then wait for the
//! other's while already holding one lock, so they deadlock; the bystander
//! keeps the process alive.

use concir_sync::Semaphore;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;

struct Locks {
    a: Mutex<u32>,
    b: Mutex<u32>,
}

fn a(locks: Arc<Locks>, sa: Arc<Semaphore>, sb: Arc<Semaphore>) -> u32 {
    let mut ga = locks.a.lock().unwrap();
    sa.post();
    sb.take();
    let gb = locks.b.lock().unwrap(); // DEFECT: deadlocks against b
    *ga += 1;
    let n = *ga;
    drop(gb);
    drop(ga);
    n
}

fn b(locks: Arc<Locks>, sa: Arc<Semaphore>, sb: Arc<Semaphore>) -> u32 {
    let mut gb = locks.b.lock().unwrap();
    sb.post();
    sa.take();
    let ga = locks.a.lock().unwrap(); // DEFECT: deadlocks against a
    *gb += 1;
    let n = *gb;
    drop(ga);
    drop(gb);
    n
}

fn bystander(flag: Arc<AtomicBool>) {
    while !flag.load(Ordering::SeqCst) {}
}

fn main() {
    let locks = Arc::new(Locks {
        a: Mutex::new(0u32),
        b: Mutex::new(0u32),
    });
    let sa = Semaphore::new(0);
    let sb = Semaphore::new(0);
    let flag = Arc::new(AtomicBool::new(false));

    let (l1, sa1, sb1) = (Arc::clone(&locks), Arc::clone(&sa), Arc::clone(&sb));
    let a = thread::spawn(move || a(l1, sa1, sb1));
    let (l2, sa2, sb2) = (Arc::clone(&locks), Arc::clone(&sa), Arc::clone(&sb));
    let b = thread::spawn(move || b(l2, sa2, sb2));
    let f = Arc::clone(&flag);
    let bystander = thread::spawn(move || bystander(f));

    let ra = a.join().unwrap();
    let rb = b.join().unwrap();
    flag.store(true, Ordering::SeqCst);
    bystander.join().unwrap();

    println!("DONE a={} b={}", ra, rb);
}
