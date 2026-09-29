//! Reference program for condvar/two_cv_two_locks.
//!
//! Matches gold.skel: w1 waits on cv1 under m1, w2 waits on cv2 under m2,
//! and each posts the semaphore `ready` (initial 0) before waiting. The
//! notifier takes `ready` twice, then holds m1 and m2 while it sets both
//! flags and wakes both condvars. Each printed value is that flag.

use concir_sync::Semaphore;
use std::sync::{Arc, Condvar, Mutex};
use std::thread;

fn w1(m1: Arc<Mutex<bool>>, cv1: Arc<Condvar>, ready: Arc<Semaphore>) -> bool {
    let mut go = m1.lock().unwrap();
    ready.post();
    while !*go {
        go = cv1.wait(go).unwrap();
    }
    *go
}

fn w2(m2: Arc<Mutex<bool>>, cv2: Arc<Condvar>, ready: Arc<Semaphore>) -> bool {
    let mut go = m2.lock().unwrap();
    ready.post();
    while !*go {
        go = cv2.wait(go).unwrap();
    }
    *go
}

fn notifier(
    m1: Arc<Mutex<bool>>,
    m2: Arc<Mutex<bool>>,
    cv1: Arc<Condvar>,
    cv2: Arc<Condvar>,
    ready: Arc<Semaphore>,
) {
    ready.take();
    ready.take();
    let mut a = m1.lock().unwrap();
    let mut b = m2.lock().unwrap();
    *a = true;
    *b = true;
    cv1.notify_all();
    cv2.notify_all();
}

fn main() {
    let m1 = Arc::new(Mutex::new(false));
    let m2 = Arc::new(Mutex::new(false));
    let cv1 = Arc::new(Condvar::new());
    let cv2 = Arc::new(Condvar::new());
    let ready = Semaphore::new(0);

    let (a1, c1, r1) = (Arc::clone(&m1), Arc::clone(&cv1), Arc::clone(&ready));
    let w1 = thread::spawn(move || w1(a1, c1, r1));
    let (a2, c2, r2) = (Arc::clone(&m2), Arc::clone(&cv2), Arc::clone(&ready));
    let w2 = thread::spawn(move || w2(a2, c2, r2));
    let (n1, n2, k1, k2, nr) = (
        Arc::clone(&m1),
        Arc::clone(&m2),
        Arc::clone(&cv1),
        Arc::clone(&cv2),
        Arc::clone(&ready),
    );
    let notifier = thread::spawn(move || notifier(n1, n2, k1, k2, nr));

    let seen1 = w1.join().unwrap();
    let seen2 = w2.join().unwrap();
    notifier.join().unwrap();
    println!("DONE w1={} w2={}", u32::from(seen1), u32::from(seen2));
}
