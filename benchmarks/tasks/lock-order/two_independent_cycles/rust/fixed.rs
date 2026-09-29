//! Reference Rust for lock-order/two_independent_cycles (SkelNet R7a-2a).
//!
//! Design: `gold.skel` has four workers over two independent lock pairs.
//! `t1`/`t2` take `a` then `b`; `t3`/`t4` take `c` then `d`. Each pair uses a
//! single order, so no pair can deadlock. Each lock protects its owner's
//! completion count, and the workers return those counts.

use std::sync::{Arc, Mutex};
use std::thread;

fn t1(a: Arc<Mutex<u32>>, b: Arc<Mutex<u32>>) -> u32 {
    let mut ga = a.lock().unwrap();
    let gb = b.lock().unwrap();
    *ga += 1;
    let n = *ga;
    drop(gb);
    drop(ga);
    n
}

fn t2(a: Arc<Mutex<u32>>, b: Arc<Mutex<u32>>) -> u32 {
    let ga = a.lock().unwrap();
    let mut gb = b.lock().unwrap();
    *gb += 1;
    let n = *gb;
    drop(gb);
    drop(ga);
    n
}

fn t3(c: Arc<Mutex<u32>>, d: Arc<Mutex<u32>>) -> u32 {
    let mut gc = c.lock().unwrap();
    let gd = d.lock().unwrap();
    *gc += 1;
    let n = *gc;
    drop(gd);
    drop(gc);
    n
}

fn t4(c: Arc<Mutex<u32>>, d: Arc<Mutex<u32>>) -> u32 {
    let gc = c.lock().unwrap();
    let mut gd = d.lock().unwrap();
    *gd += 1;
    let n = *gd;
    drop(gd);
    drop(gc);
    n
}

fn main() {
    let a = Arc::new(Mutex::new(0u32));
    let b = Arc::new(Mutex::new(0u32));
    let c = Arc::new(Mutex::new(0u32));
    let d = Arc::new(Mutex::new(0u32));

    let (a1, b1) = (Arc::clone(&a), Arc::clone(&b));
    let t1 = thread::spawn(move || t1(a1, b1));
    let (a2, b2) = (Arc::clone(&a), Arc::clone(&b));
    let t2 = thread::spawn(move || t2(a2, b2));
    let (c3, d3) = (Arc::clone(&c), Arc::clone(&d));
    let t3 = thread::spawn(move || t3(c3, d3));
    let (c4, d4) = (Arc::clone(&c), Arc::clone(&d));
    let t4 = thread::spawn(move || t4(c4, d4));

    let r1 = t1.join().unwrap();
    let r2 = t2.join().unwrap();
    let r3 = t3.join().unwrap();
    let r4 = t4.join().unwrap();
    println!("DONE t1={} t2={} t3={} t4={}", r1, r2, r3, r4);
}
