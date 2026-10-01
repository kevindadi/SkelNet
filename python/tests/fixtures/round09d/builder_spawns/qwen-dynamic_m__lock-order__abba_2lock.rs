use concir_sync::Semaphore;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::thread;

fn t1(a: Arc<Semaphore>, b: Arc<Semaphore>, count_t1: Arc<AtomicUsize>) {
    let pa = a.acquire();
    let pb = b.acquire();

    count_t1.fetch_add(1, Ordering::SeqCst);

    pb.release();
    pa.release();
    return;
}

fn t2(a: Arc<Semaphore>, b: Arc<Semaphore>, count_t2: Arc<AtomicUsize>) {
    let pa = a.acquire();
    let pb = b.acquire();

    count_t2.fetch_add(1, Ordering::SeqCst);

    pb.release();
    pa.release();
    return;
}

fn main() {
    let a = Semaphore::new_named("a", 1);
    let b = Semaphore::new_named("b", 1);

    let count_t1 = Arc::new(AtomicUsize::new(0));
    let count_t2 = Arc::new(AtomicUsize::new(0));

    let a1 = a.clone();
    let b1 = b.clone();
    let c1 = count_t1.clone();

    let handle_t1 = thread::Builder::new()
        .name("t1".to_string())
        .spawn(move || t1(a1, b1, c1))
        .unwrap();

    let a2 = a.clone();
    let b2 = b.clone();
    let c2 = count_t2.clone();

    let handle_t2 = thread::Builder::new()
        .name("t2".to_string())
        .spawn(move || t2(a2, b2, c2))
        .unwrap();

    handle_t1.join().unwrap();
    handle_t2.join().unwrap();

    println!(
        "DONE t1={} t2={}",
        count_t1.load(Ordering::SeqCst),
        count_t2.load(Ordering::SeqCst)
    );
}