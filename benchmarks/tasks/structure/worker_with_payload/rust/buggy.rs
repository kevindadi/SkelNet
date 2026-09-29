//! Defect: reading acc and writing its replacement use separate critical sections.
//! Match gold.skel: w1/w2 call the sequential computation hole while holding m.
//! compute implements the DSL extern helper; acc lives in the existing mutex.
use std::sync::{Arc, Mutex};
use std::thread;

fn compute() -> u32 {
    let mut completed = 0;
    completed += 1;
    completed
}

fn w1(m: Arc<Mutex<u32>>) {
    let previous = *m.lock().unwrap();
    let result = compute();
    let mut acc = m.lock().unwrap();
    *acc = previous + result;
}

fn w2(m: Arc<Mutex<u32>>) {
    let previous = *m.lock().unwrap();
    let result = compute();
    let mut acc = m.lock().unwrap();
    *acc = previous + result;
}

fn main() {
    let m = Arc::new(Mutex::new(0u32));
    let m1 = Arc::clone(&m);
    let w1 = thread::spawn(move || w1(m1));
    let m2 = Arc::clone(&m);
    let w2 = thread::spawn(move || w2(m2));
    w1.join().unwrap();
    w2.join().unwrap();
    let acc = *m.lock().unwrap();
    println!("DONE acc={}", acc);
}
