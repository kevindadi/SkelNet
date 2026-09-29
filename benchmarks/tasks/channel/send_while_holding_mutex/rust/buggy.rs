//! Defect program for channel/send_while_holding_mutex (SkelNet R7a-2a).
//!
//! Source: ConcPlanVerify@8bf9fa49b0300e8be00fc5c0b61a98cd8d5aa53f
//! `benchmarks/families/channel/send_while_holding_mutex/rust/buggy.rs`.
//!
//! Changes: the channel endpoint is named `ch1` at every call site, the unused
//! second channel dropped, a shared completion counter added, and the computed
//! terminal line added. The defect is unchanged: the receiver never takes the
//! value, so the sender's rendezvous send fails.

use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{mpsc, Arc};
use std::thread;

fn s(ch1: mpsc::SyncSender<u32>, done: Arc<AtomicU32>) -> u32 {
    ch1.send(1).unwrap(); // DEFECT: no receiver ever takes the value
    done.fetch_add(1, Ordering::SeqCst) + 1
}

fn r(ch1: mpsc::Receiver<u32>, done: Arc<AtomicU32>) -> u32 {
    let _ = ch1; // DEFECT: drop the receiving end without receiving
    done.fetch_add(1, Ordering::SeqCst) + 1
}

fn main() {
    let (tx, rx) = mpsc::sync_channel::<u32>(0);
    let done = Arc::new(AtomicU32::new(0));

    let (d1, d2) = (Arc::clone(&done), Arc::clone(&done));
    let s = thread::spawn(move || s(tx, d1));
    let r = thread::spawn(move || r(rx, d2));

    let _ = s.join().unwrap();
    let _ = r.join().unwrap();
    println!("DONE done={}", done.load(Ordering::SeqCst));
}
