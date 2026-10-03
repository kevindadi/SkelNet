//! Defect program for pipeline/three_stage_channels.
//!
//! Same stages, channels, values, and shared counter as fixed.rs. The defect is
//! that `stage2` keeps the shared mutex `m` locked while it pushes its values
//! downstream, and `stage3` keeps `m` locked while it drains them. When `ch2`
//! is full, `stage2` blocks on its second `send` while holding `m`, and
//! `stage3` cannot take `m` to receive, so the pipeline deadlocks. New program
//! (SkelNet R7b).

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
    let mut g = m.lock().unwrap(); // DEFECT: lock held across the downstream sends
    ch2.send(a + 1).unwrap();
    ch2.send(b + 1).unwrap();
    ch2.send(c + 1).unwrap();
    *g += 1;
    drop(g);
}

fn stage3(ch2: mpsc::Receiver<u32>, m: Arc<Mutex<u32>>) -> u32 {
    let mut g = m.lock().unwrap(); // DEFECT: lock held across the upstream receives
    let x = ch2.recv().unwrap();
    let y = ch2.recv().unwrap();
    let z = ch2.recv().unwrap();
    *g += 1;
    drop(g);
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
