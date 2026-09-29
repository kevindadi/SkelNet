//! Defect: the second worker takes b before a, preserving the ABBA wait cycle.
//! Match gold.skel: both workers hold a then b and update the protected counters.
//! Spawn plus join implements the scoped group without adding resources.
use std::sync::{Arc, Mutex};
use std::thread;

fn w1(a: Arc<Mutex<u32>>, b: Arc<Mutex<u32>>) {
    let mut ga = a.lock().unwrap();
    let mut gb = b.lock().unwrap();
    *ga += 1;
    *gb += 1;
}

fn w2(a: Arc<Mutex<u32>>, b: Arc<Mutex<u32>>) {
    let mut gb = b.lock().unwrap();
    let mut ga = a.lock().unwrap();
    *ga += 1;
    *gb += 1;
}

fn main() {
    let a = Arc::new(Mutex::new(0u32));
    let b = Arc::new(Mutex::new(0u32));
    let (a1, b1) = (Arc::clone(&a), Arc::clone(&b));
    let w1 = thread::spawn(move || w1(a1, b1));
    let (a2, b2) = (Arc::clone(&a), Arc::clone(&b));
    let w2 = thread::spawn(move || w2(a2, b2));
    w1.join().unwrap();
    w2.join().unwrap();
    let a_total = *a.lock().unwrap();
    let b_total = *b.lock().unwrap();
    println!("DONE a={} b={}", a_total, b_total);
}
