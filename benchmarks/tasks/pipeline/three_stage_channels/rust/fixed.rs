//! Reference program for pipeline/three_stage_channels.
//!
//! Three pipeline stages are connected by two capacity-one channels. `stage1`
//! feeds the values 1, 2, 3 into `ch1`; `stage2` takes them in order, adds one
//! to each, and forwards 2, 3, 4 through `ch2`; `stage3` takes the forwarded
//! values and returns their sum. A single mutex `m` protects the shared
//! `processed` counter that every stage bumps once. No stage holds `m` while it
//! blocks on a channel operation, so the pipeline always drains. The terminal
//! line is the sum that `stage3` actually computed, not a constant.

use std::sync::{mpsc, Arc, Mutex};
use std::thread;

fn stage1(ch1: mpsc::SyncSender<u32>, m: Arc<Mutex<u32>>) {
    ch1.send(1).unwrap();
    ch1.send(2).unwrap();
    ch1.send(3).unwrap();
    *m.lock().unwrap() += 1;
}

fn stage2(ch1: mpsc::Receiver<u32>, ch2: mpsc::SyncSender<u32>, m: Arc<Mutex<u32>>) {
    let a = ch1.recv().unwrap();
    let b = ch1.recv().unwrap();
    let c = ch1.recv().unwrap();
    ch2.send(a + 1).unwrap();
    ch2.send(b + 1).unwrap();
    ch2.send(c + 1).unwrap();
    *m.lock().unwrap() += 1;
}

fn stage3(ch2: mpsc::Receiver<u32>, m: Arc<Mutex<u32>>) -> u32 {
    let x = ch2.recv().unwrap();
    let y = ch2.recv().unwrap();
    let z = ch2.recv().unwrap();
    *m.lock().unwrap() += 1;
    x + y + z
}

fn main() {
    let (t1, r1) = mpsc::sync_channel::<u32>(1);
    let (t2, r2) = mpsc::sync_channel::<u32>(1);
    let m = Arc::new(Mutex::new(0u32));

    let (m1, m2) = (Arc::clone(&m), Arc::clone(&m));
    let s1 = thread::spawn(move || stage1(t1, m1));
    let s2 = thread::spawn(move || stage2(r1, t2, m2));
    let m3 = Arc::clone(&m);
    let s3 = thread::spawn(move || stage3(r2, m3));

    s1.join().unwrap();
    s2.join().unwrap();
    let total = s3.join().unwrap();
    println!("DONE sum={}", total);
}
