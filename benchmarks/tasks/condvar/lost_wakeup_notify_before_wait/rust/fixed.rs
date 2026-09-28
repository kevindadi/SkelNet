//! Reference program for condvar/lost_wakeup_notify_before_wait.
//!
//! Matches gold.skel: under `m`, the notifier stores true into `ready` and
//! then signals `cv`. The waiter waits only while `ready` is false and
//! checks it again after every wake.

use std::sync::{Arc, Condvar, Mutex};
use std::thread;

fn waiter(m: Arc<Mutex<bool>>, cv: Arc<Condvar>) -> bool {
    let mut ready = m.lock().unwrap();
    while !*ready {
        ready = cv.wait(ready).unwrap();
    }
    *ready
}

fn notifier(m: Arc<Mutex<bool>>, cv: Arc<Condvar>) {
    let mut ready = m.lock().unwrap();
    *ready = true;
    cv.notify_one();
}

fn main() {
    let m = Arc::new(Mutex::new(false));
    let cv = Arc::new(Condvar::new());
    let (m_w, cv_w) = (Arc::clone(&m), Arc::clone(&cv));
    let waiter = thread::spawn(move || waiter(m_w, cv_w));
    let (m_n, cv_n) = (Arc::clone(&m), Arc::clone(&cv));
    let notifier = thread::spawn(move || notifier(m_n, cv_n));
    let ready = waiter.join().unwrap();
    notifier.join().unwrap();
    println!("DONE ready={}", ready);
}
