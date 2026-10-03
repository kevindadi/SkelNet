//! Defect program for philosophers/dining_4_waiter.
//!
//! Same four philosophers, forks, and ids as fixed.rs, but the waiter limit is
//! dropped: there is no seat semaphore, so all four philosophers may sit at the
//! table at once. Each takes its left fork and then its right fork in the ring
//! order, which lets every philosopher hold one fork while waiting for the next
//! and the four deadlock.

use std::sync::{Arc, Mutex};
use std::thread;

fn p1(f0: Arc<Mutex<u32>>, f1: Arc<Mutex<u32>>) -> u32 {
    let _a = f0.lock().unwrap();
    let _b = f1.lock().unwrap();
    1
}

fn p2(f1: Arc<Mutex<u32>>, f2: Arc<Mutex<u32>>) -> u32 {
    let _a = f1.lock().unwrap();
    let _b = f2.lock().unwrap();
    2
}

fn p3(f2: Arc<Mutex<u32>>, f3: Arc<Mutex<u32>>) -> u32 {
    let _a = f2.lock().unwrap();
    let _b = f3.lock().unwrap();
    3
}

fn p4(f3: Arc<Mutex<u32>>, f0: Arc<Mutex<u32>>) -> u32 {
    // DEFECT: no waiter permit; f3 before f0 completes the ring.
    let _a = f3.lock().unwrap();
    let _b = f0.lock().unwrap();
    4
}

fn main() {
    let f0 = Arc::new(Mutex::new(0u32));
    let f1 = Arc::new(Mutex::new(0u32));
    let f2 = Arc::new(Mutex::new(0u32));
    let f3 = Arc::new(Mutex::new(0u32));

    let (f0a, f1a) = (Arc::clone(&f0), Arc::clone(&f1));
    let p1 = thread::spawn(move || p1(f0a, f1a));
    let (f1b, f2a) = (Arc::clone(&f1), Arc::clone(&f2));
    let p2 = thread::spawn(move || p2(f1b, f2a));
    let (f2b, f3a) = (Arc::clone(&f2), Arc::clone(&f3));
    let p3 = thread::spawn(move || p3(f2b, f3a));
    let (f3b, f0b) = (Arc::clone(&f3), Arc::clone(&f0));
    let p4 = thread::spawn(move || p4(f3b, f0b));

    let total = p1.join().unwrap()
        + p2.join().unwrap()
        + p3.join().unwrap()
        + p4.join().unwrap();
    println!("DONE sum={}", total);
}
