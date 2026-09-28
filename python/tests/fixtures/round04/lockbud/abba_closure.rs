//! Two spawn closures lock in opposite orders (a→b and b→a).
//! lockbud reports ConflictLock for this shape; both closure lines are in
//! the diagnosis spans.

use std::sync::{Arc, Mutex};
use std::thread;

fn main() {
    let a = Arc::new(Mutex::new(()));
    let b = Arc::new(Mutex::new(()));
    let (a1, b1) = (a.clone(), b.clone());
    thread::spawn(move || { let _x = a1.lock().unwrap(); let _y = b1.lock().unwrap(); });
    let (a2, b2) = (a.clone(), b.clone());
    thread::spawn(move || { let _x = b2.lock().unwrap(); let _y = a2.lock().unwrap(); });
    println!("DONE");
}
