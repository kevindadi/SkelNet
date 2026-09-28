//! Calibration fixture: correct abba written with `std::thread::scope`.
//! The instrumenter does not rewrite `s.spawn(..)`, so O4 must report
//! `instrument_unsupported` rather than a thread-count `design_loss`.

use std::sync::{Arc, Mutex};
use std::thread;

fn main() {
    let a = Arc::new(Mutex::new(()));
    let b = Arc::new(Mutex::new(()));

    thread::scope(|s| {
        let (a1, b1) = (Arc::clone(&a), Arc::clone(&b));
        s.spawn(move || {
            let _ga = a1.lock().unwrap();
            let _gb = b1.lock().unwrap();
        });
        let (a2, b2) = (Arc::clone(&a), Arc::clone(&b));
        s.spawn(move || {
            let _ga = a2.lock().unwrap();
            let _gb = b2.lock().unwrap();
        });
    });

    println!("DONE t1=1 t2=1");
}
