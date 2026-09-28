use std::sync::{Arc, Mutex};
use std::thread;

fn worker(a: Arc<Mutex<()>>, b: Arc<Mutex<()>>) { let _ga = a.lock().unwrap(); let _gb = b.lock().unwrap(); }
fn main() {
    let a = Arc::new(Mutex::new(()));
    let b = Arc::new(Mutex::new(()));
    let mut hs = Vec::new();
    for _ in 0..3 {
        let (a, b) = (Arc::clone(&a), Arc::clone(&b));
        hs.push(thread::spawn(move || worker(a, b)));
    }
    for h in hs { h.join().unwrap(); }
    println!("DONE t1=1 t2=1");
}
