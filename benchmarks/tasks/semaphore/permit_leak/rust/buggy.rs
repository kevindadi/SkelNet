//! Defect program for semaphore/permit_leak.
//!
//! w1 takes one permit and never posts it back. w2 still acquires and
//! releases once. Together with the single initial permit, w1's second
//! unmatched take cannot be satisfied, so some worker blocks forever.
//! The remaining-permit count is the same computation as fixed.rs.
//! New program (SkelNet R7a-2).

use concir_sync::Semaphore;
use std::sync::Arc;
use std::thread;

fn w1(s: Arc<Semaphore>) {
    s.take();
    s.take();
}

fn w2(s: Arc<Semaphore>) {
    let permit = s.acquire();
    drop(permit);
}

fn count_permits(s: &Semaphore) -> u32 {
    let mut left = 0u32;
    let mut held = Vec::new();
    while let Some(permit) = s.try_acquire() {
        left += 1;
        held.push(permit);
    }
    drop(held);
    left
}

fn main() {
    let s = Semaphore::new(1);
    let s1 = Arc::clone(&s);
    let w1 = thread::spawn(move || w1(s1));
    let s2 = Arc::clone(&s);
    let w2 = thread::spawn(move || w2(s2));
    w1.join().unwrap();
    w2.join().unwrap();
    let permits = count_permits(&s);
    println!("DONE permits={}", permits);
}
