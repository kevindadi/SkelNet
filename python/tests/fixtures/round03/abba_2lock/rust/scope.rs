//! Calibration fixture: both workers are now fully instrumented.
//! Anonymous worker names leave t1/t2 completion properties not_observed;
//! both lock-holding properties pass and two threads are recorded.

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
