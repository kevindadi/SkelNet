//! Defect program for semaphore/permit_leak.
//!
//! Same as fixed.rs except w1 never returns its permit: `permit.forget()`
//! consumes the permit instead of dropping it. If w1 runs first, w2 waits
//! forever for the only permit. If w2 runs first, both workers finish, but
//! the pool is left empty and the program prints `DONE permits=0`.

use concir_sync::Semaphore;
use std::sync::Arc;
use std::thread;

fn w1(s: Arc<Semaphore>) {
    let permit = s.acquire();
    permit.forget();
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
