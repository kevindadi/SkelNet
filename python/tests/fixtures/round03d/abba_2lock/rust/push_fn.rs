use std::sync::{Arc, Mutex};
use std::thread;

fn t1(a: Arc<Mutex<()>>, b: Arc<Mutex<()>>) { let _ga = a.lock().unwrap(); let _gb = b.lock().unwrap(); }
fn t2(a: Arc<Mutex<()>>, b: Arc<Mutex<()>>) { let _ga = a.lock().unwrap(); let _gb = b.lock().unwrap(); }
fn main() {
    let a = Arc::new(Mutex::new(()));
    let b = Arc::new(Mutex::new(()));
    let mut handles = Vec::new();
    let (a1, b1) = (Arc::clone(&a), Arc::clone(&b));
    handles.push(thread::spawn(move || t1(a1, b1)));
    handles.push(thread::spawn(move || t2(a, b)));
    for h in handles { h.join().unwrap(); }
    println!("DONE t1=1 t2=1");
}
