//! Reference Rust for channel/rendezvous_both_send (SkelNet R7a-2a).
//!
//! Design: `gold.skel` has a sender `s1` and a receiver `r` over the
//! zero-capacity channel `ch`. The gold declares no Mutex, so the terminal
//! value is computed with a shared atomic completion counter instead of a
//! lock.
//!
//! Newly written for SkelNet: the channel endpoint is named `ch` at both call
//! sites, the role names match the entities, a shared completion counter is
//! added, and the terminal line is computed.

use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{mpsc, Arc};
use std::thread;

fn s1(ch: mpsc::SyncSender<u32>, done: Arc<AtomicU32>) -> u32 {
    ch.send(1).unwrap();
    done.fetch_add(1, Ordering::SeqCst) + 1
}

fn r(ch: mpsc::Receiver<u32>, done: Arc<AtomicU32>) -> u32 {
    let _v = ch.recv().unwrap();
    done.fetch_add(1, Ordering::SeqCst) + 1
}

fn main() {
    let (tx, rx) = mpsc::sync_channel::<u32>(0);
    let done = Arc::new(AtomicU32::new(0));

    let (d1, d2) = (Arc::clone(&done), Arc::clone(&done));
    let s1 = thread::spawn(move || s1(tx, d1));
    let r = thread::spawn(move || r(rx, d2));

    let _ = s1.join().unwrap();
    let _ = r.join().unwrap();
    println!("DONE done={}", done.load(Ordering::SeqCst));
}
