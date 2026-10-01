//! Reference program for philosophers/dining_4_waiter.
//!
//! Four philosophers share four forks (one mutex each) laid out in a ring. Each
//! philosopher takes its left fork and then its right fork, which is a cyclic
//! order and would deadlock on its own. A `waiter` semaphore with three permits
//! admits at most three philosophers to the table, so at least one philosopher
//! can always finish and release its forks. Each philosopher returns its own id
//! and `main` prints the sum, so the terminal line is computed.

use concir_sync::Semaphore;
use std::sync::{Arc, Mutex};
use std::thread;

fn p1(waiter: Arc<Semaphore>, f0: Arc<Mutex<u32>>, f1: Arc<Mutex<u32>>) -> u32 {
    let _seat = waiter.acquire();
    let _a = f0.lock().unwrap();
    let _b = f1.lock().unwrap();
    1
}

fn p2(waiter: Arc<Semaphore>, f1: Arc<Mutex<u32>>, f2: Arc<Mutex<u32>>) -> u32 {
    let _seat = waiter.acquire();
    let _a = f1.lock().unwrap();
    let _b = f2.lock().unwrap();
    2
}

fn p3(waiter: Arc<Semaphore>, f2: Arc<Mutex<u32>>, f3: Arc<Mutex<u32>>) -> u32 {
    let _seat = waiter.acquire();
    let _a = f2.lock().unwrap();
    let _b = f3.lock().unwrap();
    3
}

fn p4(waiter: Arc<Semaphore>, f3: Arc<Mutex<u32>>, f0: Arc<Mutex<u32>>) -> u32 {
    let _seat = waiter.acquire();
    let _a = f3.lock().unwrap();
    let _b = f0.lock().unwrap();
    4
}

fn main() {
    let waiter = Semaphore::new(3);
    let f0 = Arc::new(Mutex::new(0u32));
    let f1 = Arc::new(Mutex::new(0u32));
    let f2 = Arc::new(Mutex::new(0u32));
    let f3 = Arc::new(Mutex::new(0u32));

    let (w1, f0a, f1a) = (Arc::clone(&waiter), Arc::clone(&f0), Arc::clone(&f1));
    let p1 = thread::spawn(move || p1(w1, f0a, f1a));
    let (w2, f1b, f2a) = (Arc::clone(&waiter), Arc::clone(&f1), Arc::clone(&f2));
    let p2 = thread::spawn(move || p2(w2, f1b, f2a));
    let (w3, f2b, f3a) = (Arc::clone(&waiter), Arc::clone(&f2), Arc::clone(&f3));
    let p3 = thread::spawn(move || p3(w3, f2b, f3a));
    let (w4, f3b, f0b) = (Arc::clone(&waiter), Arc::clone(&f3), Arc::clone(&f0));
    let p4 = thread::spawn(move || p4(w4, f3b, f0b));

    let total = p1.join().unwrap()
        + p2.join().unwrap()
        + p3.join().unwrap()
        + p4.join().unwrap();
    println!("DONE sum={}", total);
}
