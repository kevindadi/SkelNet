//! Calibration fixture: both workers are now fully instrumented.
//! Anonymous worker names leave t1/t2 completion properties not_observed;
//! both lock-holding properties pass and two threads are recorded.

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
