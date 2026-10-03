//! Reference program for transfer/ordered_three_accounts.
//!
//! Three accounts, each protected by its own mutex, start with one unit each.
//! Three transfer roles run at the same time: `ab` moves one unit from `a` to
//! `b`, `bc` moves one unit from `b` to `c`, and `ca` moves one unit from `c`
//! to `a`. Every role holds the source and destination mutexes at once.
//!
//! The locks are always taken in the global order a < b < c, so `ca` takes `a`
//! before `c` even though the unit flows the other way. No circular wait can
//! form and the total of the three balances is conserved.

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
    let mut ga = a.lock().unwrap();
    let mut gc = c.lock().unwrap();
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
