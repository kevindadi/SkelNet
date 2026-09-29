//! Defect program for channel/bounded_backpressure_lock_held (SkelNet R7a-2a).
//!
//! Source: ConcPlanVerify@8bf9fa49b0300e8be00fc5c0b61a98cd8d5aa53f
//! `benchmarks/families/channel/bounded_backpressure_lock_held/rust/buggy.rs`.
//!
//! Changes: handle bindings renamed to `sender`/`receiver`, the channel
//! endpoints named `ch`, the terminal line computed. The defect is unchanged:
//! both roles hold the shared lock `m` across their channel operations, so the
//! sender blocks on the full buffer while holding `m` and the receiver blocks
//! on `m`.

use std::sync::{mpsc, Arc, Mutex};
use std::thread;

struct Counts {
    sender: u32,
    receiver: u32,
}

fn sender(ch: mpsc::SyncSender<u32>, m: Arc<Mutex<Counts>>) -> u32 {
    let mut g = m.lock().unwrap(); // DEFECT: lock held across every send
    g.sender += 1;
    ch.send(1).unwrap();
    g.sender += 1;
    ch.send(2).unwrap();
    let n = g.sender;
    drop(g);
    n
}

fn receiver(ch: mpsc::Receiver<u32>, m: Arc<Mutex<Counts>>) -> u32 {
    let mut g = m.lock().unwrap(); // DEFECT: lock held across every recv
    let _v1 = ch.recv().unwrap();
    g.receiver += 1;
    let _v2 = ch.recv().unwrap();
    g.receiver += 1;
    let n = g.receiver;
    drop(g);
    n
}

fn main() {
    let (ch_tx, ch_rx) = mpsc::sync_channel::<u32>(1);
    let m = Arc::new(Mutex::new(Counts {
        sender: 0,
        receiver: 0,
    }));

    let (m1, m2) = (Arc::clone(&m), Arc::clone(&m));
    let sender = thread::spawn(move || sender(ch_tx, m1));
    let receiver = thread::spawn(move || receiver(ch_rx, m2));

    let rs = sender.join().unwrap();
    let rr = receiver.join().unwrap();
    println!("DONE sender={} receiver={}", rs, rr);
}
