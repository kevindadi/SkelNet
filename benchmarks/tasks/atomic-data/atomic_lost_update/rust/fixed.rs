//! Match gold.skel: two workers increment c through compare-and-swap retry loops.
//! The final atomic value reports completed increments; no mutex is introduced.
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::Arc;
use std::thread;

fn w1(c: Arc<AtomicU32>) {
    loop {
        let previous = c.load(Ordering::SeqCst);
        if c.compare_exchange(previous, previous + 1, Ordering::SeqCst, Ordering::SeqCst)
            .is_ok()
        {
            break;
        }
    }
}

fn w2(c: Arc<AtomicU32>) {
    loop {
        let previous = c.load(Ordering::SeqCst);
        if c.compare_exchange(previous, previous + 1, Ordering::SeqCst, Ordering::SeqCst)
            .is_ok()
        {
            break;
        }
    }
}

fn main() {
    let c = Arc::new(AtomicU32::new(0));
    let c1 = Arc::clone(&c);
    let w1 = thread::spawn(move || w1(c1));
    let c2 = Arc::clone(&c);
    let w2 = thread::spawn(move || w2(c2));
    w1.join().unwrap();
    w2.join().unwrap();
    let total = c.load(Ordering::SeqCst);
    println!("DONE c={}", total);
}
