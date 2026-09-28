use std::sync::{Arc, Mutex};
use std::thread;

fn main() {
    let a = Arc::new(Mutex::new(()));
    let b = Arc::new(Mutex::new(()));
    thread::scope(|s| {
        let t1 = s.spawn(|| { let _ga = a.lock().unwrap(); let _gb = b.lock().unwrap(); 21 });
        let t2 = s.spawn(|| { let _ga = a.lock().unwrap(); let _gb = b.lock().unwrap(); 21 });
        assert_eq!(t1.join().unwrap() + t2.join().unwrap(), 42);
    });
    println!("DONE t1=1 t2=1");
}
