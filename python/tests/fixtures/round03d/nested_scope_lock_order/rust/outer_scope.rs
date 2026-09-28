use std::sync::{Arc, Mutex};
use std::thread;

fn main() {
    let a = Arc::new(Mutex::new(()));
    let b = Arc::new(Mutex::new(()));
    thread::scope(|s| {
        let outer = s.spawn(|| {
            thread::scope(|s2| {
                let x1 = s2.spawn(|| { let _ga = a.lock().unwrap(); let _gb = b.lock().unwrap(); });
                let x2 = s2.spawn(|| { let _ga = a.lock().unwrap(); let _gb = b.lock().unwrap(); });
                x1.join().unwrap(); x2.join().unwrap();
            });
        });
        outer.join().unwrap();
    });
    println!("DONE done=1");
}
