//! Defect program for condvar/notify_one_multi_waiter_wrong_pick.
//!
//! Source: ConcPlanVerify@8bf9fa49b0300e8be00fc5c0b61a98cd8d5aa53f:benchmarks/families/condvar/notify_one_multi_waiter_wrong_pick/rust/buggy.rs
//! The defect is unchanged: the notifier uses notify_one, so one of the two
//! waiters can be left asleep. Adapted onto the gold handshake (`g12`, `gN`,
//! separate `m` and `cv`, role functions) and the same waiter count as
//! fixed.rs. `w1` still notify_all after it wakes, matching the skeleton; the
//! only difference from fixed.rs is notify_one in the notifier.

use concir_sync::Semaphore;
use std::sync::{Arc, Condvar, Mutex};
use std::thread;

struct Gate {
    go: bool,
    waiting: u32,
}

fn w1(m: Arc<Mutex<Gate>>, cv: Arc<Condvar>, g12: Arc<Semaphore>) {
    let mut gate = m.lock().unwrap();
    g12.post();
    gate.waiting += 1;
    while !gate.go {
        gate = cv.wait(gate).unwrap();
    }
    gate.waiting -= 1;
    cv.notify_all();
}

fn w2(m: Arc<Mutex<Gate>>, cv: Arc<Condvar>, g12: Arc<Semaphore>, g_n: Arc<Semaphore>) {
    g12.take();
    let mut gate = m.lock().unwrap();
    g_n.post();
    gate.waiting += 1;
    while !gate.go {
        gate = cv.wait(gate).unwrap();
    }
    gate.waiting -= 1;
}

fn notifier(m: Arc<Mutex<Gate>>, cv: Arc<Condvar>, g_n: Arc<Semaphore>) {
    g_n.take();
    let mut gate = m.lock().unwrap();
    gate.go = true;
    cv.notify_one();
}

fn main() {
    let m = Arc::new(Mutex::new(Gate { go: false, waiting: 0 }));
    let cv = Arc::new(Condvar::new());
    let g12 = Semaphore::new(0);
    let gN = Semaphore::new(0);

    let (m1, cv1, g12_1) = (Arc::clone(&m), Arc::clone(&cv), Arc::clone(&g12));
    let w1 = thread::spawn(move || w1(m1, cv1, g12_1));
    let (m2, cv2, g12_2, gn2) = (
        Arc::clone(&m),
        Arc::clone(&cv),
        Arc::clone(&g12),
        Arc::clone(&gN),
    );
    let w2 = thread::spawn(move || w2(m2, cv2, g12_2, gn2));
    let (m3, cv3, gn3) = (Arc::clone(&m), Arc::clone(&cv), Arc::clone(&gN));
    let notifier = thread::spawn(move || notifier(m3, cv3, gn3));

    w1.join().unwrap();
    w2.join().unwrap();
    notifier.join().unwrap();
    let waiters = m.lock().unwrap().waiting;
    println!("DONE waiters={}", waiters);
}
