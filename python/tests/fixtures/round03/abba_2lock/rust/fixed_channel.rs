//! Calibration fixture: correct abba plus an `mpsc` channel collecting results.
//! The channel endpoints (`tx`/`rx`) cannot be name-mapped to the contract, and
//! gold declares no channel; O4 must still pass (Channel is not counted by the
//! `extra_sync` rule, and the threads are instrumented normally).

use std::sync::{mpsc, Arc, Mutex};
use std::thread;

fn t1(a: Arc<Mutex<()>>, b: Arc<Mutex<()>>, tx: mpsc::Sender<i32>) {
    let ga = a.lock().unwrap();
    let gb = b.lock().unwrap();
    drop(gb);
    drop(ga);
    let _ = tx.send(1);
}

fn t2(a: Arc<Mutex<()>>, b: Arc<Mutex<()>>, tx: mpsc::Sender<i32>) {
    let ga = a.lock().unwrap();
    let gb = b.lock().unwrap();
    drop(gb);
    drop(ga);
    let _ = tx.send(1);
}

fn main() {
    let a = Arc::new(Mutex::new(()));
    let b = Arc::new(Mutex::new(()));
    let (tx, rx) = mpsc::channel::<i32>();

    let w1 = {
        let a = Arc::clone(&a);
        let b = Arc::clone(&b);
        let tx = tx.clone();
        thread::spawn(move || t1(a, b, tx))
    };
    let w2 = {
        let a = Arc::clone(&a);
        let b = Arc::clone(&b);
        let tx = tx.clone();
        thread::spawn(move || t2(a, b, tx))
    };
    drop(tx);

    let total: i32 = rx.iter().sum();
    w1.join().unwrap();
    w2.join().unwrap();
    println!("DONE t1=1 t2=1");
    let _ = total;
}
