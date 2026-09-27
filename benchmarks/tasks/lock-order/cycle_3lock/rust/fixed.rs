//! Reference Rust for tests/e2e/three_way_deadlock/fixed.json.
//! Fix: every worker acquires mutexes following the global order a < b < c,
//! so no circular wait can form. Statement structure mirrors fixed.json:
//! w1 takes (a,b); w2 takes (a,b) then (b,c); w3 takes (a,b,c).

use std::sync::{Arc, Mutex};
use std::thread;

fn main() {
    let mtx_a = Arc::new(Mutex::new(()));
    let mtx_b = Arc::new(Mutex::new(()));
    let mtx_c = Arc::new(Mutex::new(()));

    let (a1, b1) = (Arc::clone(&mtx_a), Arc::clone(&mtx_b));
    let w1 = thread::spawn(move || {
        let ga = a1.lock().unwrap(); // s1: lock mtx_a
        let gb = b1.lock().unwrap(); // s2: lock mtx_b
        drop(gb); // s3
        drop(ga); // s4
    });

    let (a2, b2, c2) = (
        Arc::clone(&mtx_a),
        Arc::clone(&mtx_b),
        Arc::clone(&mtx_c),
    );
    let w2 = thread::spawn(move || {
        let ga = a2.lock().unwrap(); // s1: lock mtx_a
        let gb = b2.lock().unwrap(); // s2: lock mtx_b
        drop(gb); // s3
        drop(ga); // s4
        let gb = b2.lock().unwrap(); // s5: lock mtx_b
        let gc = c2.lock().unwrap(); // s6: lock mtx_c
        drop(gc); // s7
        drop(gb); // s8
    });

    let (a3, b3, c3) = (
        Arc::clone(&mtx_a),
        Arc::clone(&mtx_b),
        Arc::clone(&mtx_c),
    );
    let w3 = thread::spawn(move || {
        let ga = a3.lock().unwrap(); // s1: lock mtx_a
        let gb = b3.lock().unwrap(); // s2: lock mtx_b
        let gc = c3.lock().unwrap(); // s3: lock mtx_c
        drop(gc); // s4
        drop(gb); // s5
        drop(ga); // s6
    });

    w1.join().unwrap();
    w2.join().unwrap();
    w3.join().unwrap();
}
