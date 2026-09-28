use std::sync::{Arc, Mutex};
use std::thread;

fn outer(a: Arc<Mutex<()>>, b: Arc<Mutex<()>>) {
        let (a1, b1) = (Arc::clone(&a), Arc::clone(&b));
        let x1 = thread::spawn(move || { let _ga = a1.lock().unwrap(); let _gb = b1.lock().unwrap(); });
        let x2 = thread::spawn(move || { let _ga = a.lock().unwrap(); let _gb = b.lock().unwrap(); });
        x1.join().unwrap(); x2.join().unwrap();
}
fn main() {
    let a = Arc::new(Mutex::new(()));
    let b = Arc::new(Mutex::new(()));
    let h = thread::spawn(move || outer(a, b));
    h.join().unwrap();
    println!("DONE done=1");
}
