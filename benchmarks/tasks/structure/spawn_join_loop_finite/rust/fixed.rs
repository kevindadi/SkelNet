//! Two finite iterations of gold.skel's spawn-worker/join loop.
//! Join results count completed activations without shared resources.
use std::thread;

fn worker() -> u32 {
    let mut completed = 0;
    completed += 1;
    completed
}

fn main() {
    let mut workers = 0;
    for _ in 0..2 {
        let worker = thread::spawn(move || worker());
        workers += worker.join().unwrap();
    }
    println!("DONE workers={}", workers);
}
