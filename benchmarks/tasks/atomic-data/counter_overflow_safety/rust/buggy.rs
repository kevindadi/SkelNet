//! Defect: w1 ignores the upper limit and can increment c beyond one.
//! Match gold.skel: w1/w2 update c inside m, and main joins both workers.
//! The conditional increment preserves the tighter upper limit of one.
use std::sync::{Arc, Mutex};
use std::thread;

fn w1(m: Arc<Mutex<u32>>) {
    let mut c = m.lock().unwrap();
    *c += 1;
}

fn w2(m: Arc<Mutex<u32>>) {
    let mut c = m.lock().unwrap();
    if *c < 1 {
        *c += 1;
    }
}

fn main() {
    let m = Arc::new(Mutex::new(0u32));
    let m1 = Arc::clone(&m);
    let w1 = thread::spawn(move || w1(m1));
    let m2 = Arc::clone(&m);
    let w2 = thread::spawn(move || w2(m2));
    w1.join().unwrap();
    w2.join().unwrap();
    let c = *m.lock().unwrap();
    println!("DONE c={}", c);
}
