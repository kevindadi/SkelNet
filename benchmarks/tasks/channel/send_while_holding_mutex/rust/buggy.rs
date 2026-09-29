//! Defect program for channel/send_while_holding_mutex (SkelNet R7a-2a).
//!
//! Source: ConcPlanVerify@8bf9fa49b0300e8be00fc5c0b61a98cd8d5aa53f
//! `benchmarks/families/channel/send_while_holding_mutex/rust/buggy.rs`.
//!
//! The original receiver closure is `let _ = rx1;`. In edition 2021 that
//! wildcard does not capture `rx1`, so the endpoint is dropped immediately and
//! the sender blocks forever (the original hangs). ConcPlanVerify's
//! `buggy.cir.json` (`channel_deadlock`) instead has `s` send on `ch1` while
//! `r` receives on `ch2`: a rendezvous mismatch. This program restores that
//! mismatch — each idle endpoint stays alive in `main` until after the joins,
//! so neither blocked task is ever disconnected and the pair deadlocks.
//!
//! Only the naming (entities `s`/`r`/`ch1`/`ch2`), the shared completion
//! counter and the computed terminal line are additions on top of that defect.

use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{mpsc, Arc};
use std::thread;

fn s(ch1: mpsc::SyncSender<u32>, done: Arc<AtomicU32>) -> u32 {
    ch1.send(1).unwrap(); // DEFECT: `r` receives on ch2, so this send never pairs
    done.fetch_add(1, Ordering::SeqCst) + 1
}

fn r(ch2: mpsc::Receiver<u32>, done: Arc<AtomicU32>) -> u32 {
    let _v = ch2.recv().unwrap(); // DEFECT: `s` sends on ch1, so nothing arrives
    done.fetch_add(1, Ordering::SeqCst) + 1
}

fn main() {
    let (tx1, _rx1) = mpsc::sync_channel::<u32>(0);
    let (_tx2, rx2) = mpsc::sync_channel::<u32>(0);
    let done = Arc::new(AtomicU32::new(0));

    let (d1, d2) = (Arc::clone(&done), Arc::clone(&done));
    let s = thread::spawn(move || s(tx1, d1));
    let r = thread::spawn(move || r(rx2, d2));

    let _ = s.join().unwrap();
    let _ = r.join().unwrap();
    println!("DONE done={}", done.load(Ordering::SeqCst));
}
