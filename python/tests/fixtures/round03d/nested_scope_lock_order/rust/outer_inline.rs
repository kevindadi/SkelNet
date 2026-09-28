use std::sync::{Arc, Mutex};
use std::thread;

fn main() {
    let a = Arc::new(Mutex::new(()));
    let b = Arc::new(Mutex::new(()));
    let outer = thread::spawn(move || {
        let (a1, b1) = (Arc::clone(&a), Arc::clone(&b));
        let x1 = thread::spawn(move || { let _ga = a1.lock().unwrap(); let _gb = b1.lock().unwrap(); });
        let x2 = thread::spawn(move || { let _ga = a.lock().unwrap(); let _gb = b.lock().unwrap(); });
        x1.join().unwrap(); x2.join().unwrap();
    });
    outer.join().unwrap();
    println!("DONE done=1");
}
