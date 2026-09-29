//! Reference program for condvar/notify_one_multi_waiter_wrong_pick.
//!
//! Matches gold.skel. `g12` and `gN` (both start at 0) order entry: w1 posts
//! `g12` and waits; w2 takes `g12`, posts `gN`, and waits; the notifier takes
//! `gN` and then, holding `m`, marks `go` and wakes every waiter with
//! notify_all. `w1` also notify_all after it proceeds, as in the skeleton.
//! The printed waiter count is the `waiting` field left in `m`.
//!
//! Rewritten from the Arc<(Mutex, Condvar)> loop that printed a constant and
//! omitted `g12` and `gN`.

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
    cv.notify_all();
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
