//! Defect program for transfer/ordered_three_warehouses.
//!
//! Same three warehouses, starting stock, shipping roles, and computed
//! terminal line as fixed.rs. The defect is that `ship_wn` takes the
//! destination dock `north` first and then the source dock `west`, so the
//! three roles take their two docks in the cycle north -> south -> west ->
//! north. All three can hold one dock and wait forever for the next, and the
//! program can hang. New program (SkelNet R7b).

use std::sync::{Arc, Mutex};
use std::thread;

fn ship_ns(north: Arc<Mutex<i32>>, south: Arc<Mutex<i32>>) {
    let mut gn = north.lock().unwrap();
    let mut gs = south.lock().unwrap();
    *gn -= 1;
    *gs += 1;
}

fn ship_sw(south: Arc<Mutex<i32>>, west: Arc<Mutex<i32>>) {
    let mut gs = south.lock().unwrap();
    let mut gw = west.lock().unwrap();
    *gs -= 1;
    *gw += 1;
}

fn ship_wn(north: Arc<Mutex<i32>>, west: Arc<Mutex<i32>>) {
    // DEFECT: takes west then north, closing the cycle north -> south -> west -> north.
    let mut gw = west.lock().unwrap();
    let mut gn = north.lock().unwrap();
    *gw -= 1;
    *gn += 1;
}

fn main() {
    let north = Arc::new(Mutex::new(1i32));
    let south = Arc::new(Mutex::new(1i32));
    let west = Arc::new(Mutex::new(1i32));

    let (n1, s1) = (Arc::clone(&north), Arc::clone(&south));
    let ship_ns = thread::spawn(move || ship_ns(n1, s1));
    let (s2, w2) = (Arc::clone(&south), Arc::clone(&west));
    let ship_sw = thread::spawn(move || ship_sw(s2, w2));
    let (n3, w3) = (Arc::clone(&north), Arc::clone(&west));
    let ship_wn = thread::spawn(move || ship_wn(n3, w3));

    ship_ns.join().unwrap();
    ship_sw.join().unwrap();
    ship_wn.join().unwrap();

    let total = *north.lock().unwrap() + *south.lock().unwrap() + *west.lock().unwrap();
    println!("DONE crates={}", total);
}
