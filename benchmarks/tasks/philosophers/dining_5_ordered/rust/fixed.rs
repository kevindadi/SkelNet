//! Reference program for philosophers/dining_5_ordered.
//!
//! Five philosophers share five forks (one mutex each). Each philosopher must
//! hold both of the forks beside it at the same time while it eats. To rule out
//! deadlock, every philosopher takes its two forks in the same global order
//! `f0 < f1 < f2 < f3 < f4`: `p5` owns `f4` and `f0` but still takes `f0`
//! first. Each philosopher returns its own id and `main` prints the sum, so the
//! terminal line is computed from the workers rather than written literally.

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
    // Global order: take f0 before f4 even though f4 is p5's other fork.
    let _a = f0.lock().unwrap();
    let _b = f4.lock().unwrap();
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
