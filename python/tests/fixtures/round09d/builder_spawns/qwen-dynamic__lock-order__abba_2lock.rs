use std::sync::{Arc, Mutex};
use std::thread;

struct CompletionCounts {
    t1: usize,
    t2: usize,
}

struct SharedLocks {
    a: Mutex<()>,
    b: Mutex<CompletionCounts>,
}

fn t1(shared: Arc<SharedLocks>) {
    let a_guard = shared.a.lock().unwrap();
    let mut counts_guard = shared.b.lock().unwrap();

    counts_guard.t1 += 1;

    drop(counts_guard);
    drop(a_guard);
}

fn t2(shared: Arc<SharedLocks>) {
    let a_guard = shared.a.lock().unwrap();
    let mut counts_guard = shared.b.lock().unwrap();

    counts_guard.t2 += 1;

    drop(counts_guard);
    drop(a_guard);
}

fn main() {
    let shared = Arc::new(SharedLocks {
        a: Mutex::new(()),
        b: Mutex::new(CompletionCounts { t1: 0, t2: 0 }),
    });

    let shared_t1 = Arc::clone(&shared);
    let handle_t1 = thread::Builder::new()
        .name("t1".to_string())
        .spawn(move || t1(shared_t1))
        .unwrap();

    let shared_t2 = Arc::clone(&shared);
    let handle_t2 = thread::Builder::new()
        .name("t2".to_string())
        .spawn(move || t2(shared_t2))
        .unwrap();

    handle_t1.join().unwrap();
    handle_t2.join().unwrap();

    let counts = shared.b.lock().unwrap();
    println!("DONE t1={} t2={}", counts.t1, counts.t2);
}