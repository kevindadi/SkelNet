//! Defect program for philosophers/dining_5_ordered.
//!
//! Same five philosophers and five forks as fixed.rs. The defect is the
//! natural first-try formulation: each philosopher simply takes its left fork
//! and then its right fork. `p1`..`p4` happen to take `f0 < f1 < f2 < f3 < f4`,
//! but `p5`'s left fork is `f4` and its right fork is `f0`, so `p5` takes `f4`
//! before `f0`. That cyclic order lets every philosopher hold one fork while
//! waiting for the next, and the five can deadlock.

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

fn p4(f3: Arc<Mutex<u32>>, f4: Arc<Mutex<u32>>) -> u32 {
    let _a = f3.lock().unwrap();
    let _b = f4.lock().unwrap();
    4
}

fn p5(f0: Arc<Mutex<u32>>, f4: Arc<Mutex<u32>>) -> u32 {
    // DEFECT: left fork (f4) before right fork (f0), the opposite global order.
    let _b = f4.lock().unwrap();
    let _a = f0.lock().unwrap();
    5
}

fn main() {
    let f0 = Arc::new(Mutex::new(0u32));
    let f1 = Arc::new(Mutex::new(0u32));
    let f2 = Arc::new(Mutex::new(0u32));
    let f3 = Arc::new(Mutex::new(0u32));
    let f4 = Arc::new(Mutex::new(0u32));

    let (f0a, f1a) = (Arc::clone(&f0), Arc::clone(&f1));
    let p1 = thread::spawn(move || p1(f0a, f1a));
    let (f1b, f2a) = (Arc::clone(&f1), Arc::clone(&f2));
    let p2 = thread::spawn(move || p2(f1b, f2a));
    let (f2b, f3a) = (Arc::clone(&f2), Arc::clone(&f3));
    let p3 = thread::spawn(move || p3(f2b, f3a));
    let (f3b, f4a) = (Arc::clone(&f3), Arc::clone(&f4));
    let p4 = thread::spawn(move || p4(f3b, f4a));
    let (f0b, f4b) = (Arc::clone(&f0), Arc::clone(&f4));
    let p5 = thread::spawn(move || p5(f0b, f4b));

    let total = p1.join().unwrap()
        + p2.join().unwrap()
        + p3.join().unwrap()
        + p4.join().unwrap()
        + p5.join().unwrap();
    println!("DONE sum={}", total);
}
