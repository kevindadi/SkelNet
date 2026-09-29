//! Defect program for channel/rendezvous_both_send (SkelNet R7a-2a).
//!
//! Newly written for SkelNet. The typical error implementation has both roles
//! send on the zero-capacity channel `ch`, so no receive ever pairs with a
//! send and both tasks block forever. The program computes the same terminal
//! line as the reference but never reaches it.

use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{mpsc, Arc};
use std::thread;

fn s1(ch: mpsc::SyncSender<u32>, done: Arc<AtomicU32>) -> u32 {
    ch.send(1).unwrap();
    done.fetch_add(1, Ordering::SeqCst) + 1
}

fn r(ch: mpsc::SyncSender<u32>, done: Arc<AtomicU32>) -> u32 {
    // DEFECT: the receiver role sends instead of receiving, so no send pairs.
    ch.send(2).unwrap();
    done.fetch_add(1, Ordering::SeqCst) + 1
}

fn main() {
    let (tx, _rx) = mpsc::sync_channel::<u32>(0);
    let done = Arc::new(AtomicU32::new(0));

    let tx2 = tx.clone();
    let (d1, d2) = (Arc::clone(&done), Arc::clone(&done));
    let s1 = thread::spawn(move || s1(tx, d1));
    let r = thread::spawn(move || r(tx2, d2));

    let _ = s1.join().unwrap();
    let _ = r.join().unwrap();
    println!("DONE done={}", done.load(Ordering::SeqCst));
}
