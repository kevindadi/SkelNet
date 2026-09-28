//! Defect program for condvar/lost_wakeup_notify_before_wait.
//!
//! The notifier signals `cv` before it stores true into `ready`, and the
//! waiter waits once without checking the flag. A signal that runs first is
//! lost, and the waiter then blocks even though the flag becomes true.
//! New program (SkelNet R7a-2); there was no imported buggy.rs for this task.

use std::sync::{Arc, Condvar, Mutex};
use std::thread;

fn waiter(m: Arc<Mutex<bool>>, cv: Arc<Condvar>) -> bool {
    let ready = m.lock().unwrap();
    let ready = cv.wait(ready).unwrap();
    *ready
}

fn notifier(m: Arc<Mutex<bool>>, cv: Arc<Condvar>) {
    cv.notify_one();
    let mut ready = m.lock().unwrap();
    *ready = true;
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
