//! Defect program for philosophers/toolbay_5_ordered (disguised).
//!
//! Same five robots and five tool bays as fixed.rs. The defect is the natural
//! first-try formulation: each robot claims its first bay and then its second
//! bay in ring order. `r1`..`r4` happen to claim `bay0 < bay1 < bay2 < bay3 <
//! bay4`, but `r5` claims `bay4` before `bay0`, so the robots can each hold one
//! bay while waiting for the next and the five can deadlock.

use std::sync::{Arc, Mutex};
use std::thread;

fn r1(bay0: Arc<Mutex<u32>>, bay1: Arc<Mutex<u32>>) -> u32 {
    let _a = bay0.lock().unwrap();
    let _b = bay1.lock().unwrap();
    1
}

fn r2(bay1: Arc<Mutex<u32>>, bay2: Arc<Mutex<u32>>) -> u32 {
    let _a = bay1.lock().unwrap();
    let _b = bay2.lock().unwrap();
    2
}

fn r3(bay2: Arc<Mutex<u32>>, bay3: Arc<Mutex<u32>>) -> u32 {
    let _a = bay2.lock().unwrap();
    let _b = bay3.lock().unwrap();
    3
}

fn r4(bay3: Arc<Mutex<u32>>, bay4: Arc<Mutex<u32>>) -> u32 {
    let _a = bay3.lock().unwrap();
    let _b = bay4.lock().unwrap();
    4
}

fn r5(bay0: Arc<Mutex<u32>>, bay4: Arc<Mutex<u32>>) -> u32 {
    // DEFECT: bay4 before bay0, the opposite global order.
    let _b = bay4.lock().unwrap();
    let _a = bay0.lock().unwrap();
    5
}

fn main() {
    let bay0 = Arc::new(Mutex::new(0u32));
    let bay1 = Arc::new(Mutex::new(0u32));
    let bay2 = Arc::new(Mutex::new(0u32));
    let bay3 = Arc::new(Mutex::new(0u32));
    let bay4 = Arc::new(Mutex::new(0u32));

    let (b0a, b1a) = (Arc::clone(&bay0), Arc::clone(&bay1));
    let r1 = thread::spawn(move || r1(b0a, b1a));
    let (b1b, b2a) = (Arc::clone(&bay1), Arc::clone(&bay2));
    let r2 = thread::spawn(move || r2(b1b, b2a));
    let (b2b, b3a) = (Arc::clone(&bay2), Arc::clone(&bay3));
    let r3 = thread::spawn(move || r3(b2b, b3a));
    let (b3b, b4a) = (Arc::clone(&bay3), Arc::clone(&bay4));
    let r4 = thread::spawn(move || r4(b3b, b4a));
    let (b0b, b4b) = (Arc::clone(&bay0), Arc::clone(&bay4));
    let r5 = thread::spawn(move || r5(b0b, b4b));

    let total = r1.join().unwrap()
        + r2.join().unwrap()
        + r3.join().unwrap()
        + r4.join().unwrap()
        + r5.join().unwrap();
    println!("DONE sum={}", total);
}
