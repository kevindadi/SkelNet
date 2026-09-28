//! Calibration fixture: correct abba whose spawns live in `handles.push(...)`.
//! The instrumenter only rewrites `let`-initializer spawns, so O4 must report
//! `instrument_unsupported` rather than a thread-count `design_loss`.

use std::sync::{Arc, Mutex};
use std::thread;

fn main() {
    let a = Arc::new(Mutex::new(()));
    let b = Arc::new(Mutex::new(()));

    let mut handles = Vec::new();
    for _ in 0..2 {
        let a = Arc::clone(&a);
        let b = Arc::clone(&b);
        handles.push(thread::spawn(move || {
            let _ga = a.lock().unwrap();
            let _gb = b.lock().unwrap();
        }));
    }
    for handle in handles {
        handle.join().unwrap();
    }

    println!("DONE t1=1 t2=1");
}
