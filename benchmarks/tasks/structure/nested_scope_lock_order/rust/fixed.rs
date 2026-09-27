use std::sync::{Arc, Condvar, Mutex, mpsc};
use std::thread;

fn main() {
    let a=Arc::new(Mutex::new(())); let b=Arc::new(Mutex::new(()));
    let (a1,b1)=(Arc::clone(&a),Arc::clone(&b));
    let x1=thread::spawn(move||{ let _ga=a1.lock().unwrap(); let _gb=b1.lock().unwrap(); });
    let (a2,b2)=(Arc::clone(&a),Arc::clone(&b));
    let x2=thread::spawn(move||{ let _ga=a2.lock().unwrap(); let _gb=b2.lock().unwrap(); });
    x1.join().unwrap(); x2.join().unwrap();
    println!("DONE done=1");
}
