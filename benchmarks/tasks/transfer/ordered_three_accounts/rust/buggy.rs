//! Defect program for transfer/ordered_three_accounts.
//!
//! Same three accounts, starting balances, transfer roles, and computed
//! terminal line as fixed.rs. The defect is that `ca` takes the destination
//! lock `a` first and then the source lock `c`, so the three roles take their
//! two locks in the cycle a -> b -> c -> a. All three can hold one lock and
//! wait forever for the next, and the program can hang. New program
//! (SkelNet R7b).

use std::sync::{Arc, Mutex};
use std::thread;

fn ab(a: Arc<Mutex<i32>>, b: Arc<Mutex<i32>>) {
    let mut ga = a.lock().unwrap();
    let mut gb = b.lock().unwrap();
    *ga -= 1;
    *gb += 1;
}

fn bc(b: Arc<Mutex<i32>>, c: Arc<Mutex<i32>>) {
    let mut gb = b.lock().unwrap();
    let mut gc = c.lock().unwrap();
    *gb -= 1;
    *gc += 1;
}

fn ca(a: Arc<Mutex<i32>>, c: Arc<Mutex<i32>>) {
    // DEFECT: takes c then a, closing the cycle a -> b -> c -> a.
    let mut gc = c.lock().unwrap();
    let mut ga = a.lock().unwrap();
    *gc -= 1;
    *ga += 1;
}

fn main() {
    let a = Arc::new(Mutex::new(1i32));
    let b = Arc::new(Mutex::new(1i32));
    let c = Arc::new(Mutex::new(1i32));

    let (a1, b1) = (Arc::clone(&a), Arc::clone(&b));
    let ab = thread::spawn(move || ab(a1, b1));
    let (b2, c2) = (Arc::clone(&b), Arc::clone(&c));
    let bc = thread::spawn(move || bc(b2, c2));
    let (a3, c3) = (Arc::clone(&a), Arc::clone(&c));
    let ca = thread::spawn(move || ca(a3, c3));

    ab.join().unwrap();
    bc.join().unwrap();
    ca.join().unwrap();

    let total = *a.lock().unwrap() + *b.lock().unwrap() + *c.lock().unwrap();
    println!("DONE total={}", total);
}
