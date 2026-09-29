//! Reference Rust for channel/send_while_holding_mutex (SkelNet R7a-2a).
//!
//! Design: `gold.skel` has a `s` and an `r` over the zero-capacity channel
//! `ch1` (the declared `ch2` is unused by the gold design). The gold declares
//! no Mutex, so the terminal value is computed with a shared atomic completion
//! counter instead of a lock.
//!
//! Rewritten from the ConcPlanVerify reference: the channel endpoint is named
//! `ch1` at both call sites, a shared completion counter is added, and the
//! terminal line is computed.

use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{mpsc, Arc};
use std::thread;

fn s(ch1: mpsc::SyncSender<u32>, done: Arc<AtomicU32>) -> u32 {
    ch1.send(1).unwrap();
    done.fetch_add(1, Ordering::SeqCst) + 1
}

fn r(ch1: mpsc::Receiver<u32>, done: Arc<AtomicU32>) -> u32 {
    let _v = ch1.recv().unwrap();
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
