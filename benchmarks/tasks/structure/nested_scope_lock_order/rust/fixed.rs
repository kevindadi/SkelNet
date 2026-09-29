//! Match gold.skel: both workers hold a then b and update the protected counters.
//! Rewritten reference: outer now starts and joins x1/x2; output is computed.
use std::sync::{Arc, Mutex};
use std::thread;

fn x1(a: Arc<Mutex<u32>>, b: Arc<Mutex<u32>>) {
    let mut ga = a.lock().unwrap();
    let mut gb = b.lock().unwrap();
    *ga += 1;
    *gb += 1;
}

fn x2(a: Arc<Mutex<u32>>, b: Arc<Mutex<u32>>) {
    let mut ga = a.lock().unwrap();
    let mut gb = b.lock().unwrap();
    *ga += 1;
    *gb += 1;
}

fn outer(a: Arc<Mutex<u32>>, b: Arc<Mutex<u32>>) {
    let (a1, b1) = (Arc::clone(&a), Arc::clone(&b));
    let x1 = thread::spawn(move || x1(a1, b1));
    let (a2, b2) = (Arc::clone(&a), Arc::clone(&b));
    let x2 = thread::spawn(move || x2(a2, b2));
    x1.join().unwrap();
    x2.join().unwrap();
}

fn main() {
    let a = Arc::new(Mutex::new(0u32));
    let b = Arc::new(Mutex::new(0u32));
    let (a_outer, b_outer) = (Arc::clone(&a), Arc::clone(&b));
    let outer = thread::spawn(move || outer(a_outer, b_outer));
    outer.join().unwrap();
    let a_total = *a.lock().unwrap();
    let b_total = *b.lock().unwrap();
    println!("DONE a={} b={}", a_total, b_total);
}
