//! Defect program for lock-order/two_independent_cycles (SkelNet R7a-2a).
//!
//! Newly written for SkelNet. The typical error implementation reverses the
//! lock order inside both independent pairs, so each pair forms its own
//! two-lock cycle (`t1` a->b vs `t2` b->a, `t3` c->d vs `t4` d->c). The two
//! cycles can deadlock independently, and the program still computes and
//! would print the same terminal line as the reference.

use std::sync::{Arc, Mutex};
use std::thread;

fn t1(a: Arc<Mutex<u32>>, b: Arc<Mutex<u32>>) -> u32 {
    let mut ga = a.lock().unwrap();
    *ga += 1;
    let n = *ga;
    let gb = b.lock().unwrap();
    let _ = &*gb;
    drop(gb);
    drop(ga);
    n
}

fn t2(a: Arc<Mutex<u32>>, b: Arc<Mutex<u32>>) -> u32 {
    // DEFECT: opposite order inside the first pair.
    let mut gb = b.lock().unwrap();
    *gb += 1;
    let n = *gb;
    let ga = a.lock().unwrap();
    let _ = &*ga;
    drop(ga);
    drop(gb);
    n
}

fn t3(c: Arc<Mutex<u32>>, d: Arc<Mutex<u32>>) -> u32 {
    let mut gc = c.lock().unwrap();
    *gc += 1;
    let n = *gc;
    let gd = d.lock().unwrap();
    let _ = &*gd;
    drop(gd);
    drop(gc);
    n
}

fn t4(c: Arc<Mutex<u32>>, d: Arc<Mutex<u32>>) -> u32 {
    // DEFECT: opposite order inside the second pair.
    let mut gd = d.lock().unwrap();
    *gd += 1;
    let n = *gd;
    let gc = c.lock().unwrap();
    let _ = &*gc;
    drop(gc);
    drop(gd);
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
