use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::thread;

fn w1(c: Arc<AtomicUsize>) {
    c.fetch_add(1, Ordering::SeqCst);
}

fn w2(c: Arc<AtomicUsize>) {
    c.fetch_add(1, Ordering::SeqCst);
}

fn main() {
    let c = Arc::new(AtomicUsize::new(0));

    let c_for_w1 = Arc::clone(&c);
    let h1 = thread::Builder::new()
        .name("w1".to_string())
        .spawn(move || w1(c_for_w1))
        .expect("failed to spawn w1");

    let c_for_w2 = Arc::clone(&c);
    let h2 = thread::Builder::new()
        .name("w2".to_string())
        .spawn(move || w2(c_for_w2))
        .expect("failed to spawn w2");

    h1.join().expect("w1 panicked");
    h2.join().expect("w2 panicked");

    let final_c = c.load(Ordering::SeqCst);
    println!("DONE c={}", final_c);
}