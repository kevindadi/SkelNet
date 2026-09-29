//! Reference Rust for channel/bounded_backpressure_lock_held (SkelNet R7a-2a).
//!
//! Design: `gold.skel` has a `sender` and a `receiver` over a capacity-one
//! channel `ch`, plus one shared lock `m`. Neither role waits on the channel
//! while holding `m`, so the bounded buffer never deadlocks. `m` protects two
//! counters; each role bumps its own counter once per value and returns it, so
//! the terminal line is computed from synchronised state.
//!
//! Rewritten from the ConcPlanVerify reference: handle bindings renamed to
//! `sender`/`receiver`, the channel endpoints named `ch` at every call site,
//! the lock `m` added, and the terminal line computed.

use std::sync::{mpsc, Arc, Mutex};
use std::thread;

struct Counts {
    sender: u32,
    receiver: u32,
}

fn sender(ch: mpsc::SyncSender<u32>, m: Arc<Mutex<Counts>>) -> u32 {
    m.lock().unwrap().sender += 1;
    ch.send(1).unwrap();
    m.lock().unwrap().sender += 1;
    ch.send(2).unwrap();
    let n = m.lock().unwrap().sender;
    n
}

fn receiver(ch: mpsc::Receiver<u32>, m: Arc<Mutex<Counts>>) -> u32 {
    let _v1 = ch.recv().unwrap();
    m.lock().unwrap().receiver += 1;
    let _v2 = ch.recv().unwrap();
    m.lock().unwrap().receiver += 1;
    let n = m.lock().unwrap().receiver;
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
