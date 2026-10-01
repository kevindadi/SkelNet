//! Reference program for shutdown/graceful_workers.
//!
//! A producer puts four tasks (values 1, 2, 3, 4) into a capacity-one work
//! channel and then signals shutdown by posting one `stop` permit for each of
//! the two workers. Both workers share the work channel, take two tasks each,
//! then take one shutdown permit and exit. A shared mutex `m` protects the
//! `finished` counter. Because the producer posts as many permits as there are
//! workers, every worker can stop and the program always terminates. The
//! terminal line is the sum of the task values the two workers actually took,
//! not a constant.

use concir_sync::Semaphore;
use std::sync::{mpsc, Arc, Mutex};
use std::thread;

fn producer(jobs: mpsc::SyncSender<u32>, stop: Arc<Semaphore>, m: Arc<Mutex<u32>>) {
    jobs.send(1).unwrap();
    jobs.send(2).unwrap();
    jobs.send(3).unwrap();
    jobs.send(4).unwrap();
    stop.post();
    stop.post();
    *m.lock().unwrap() += 1;
}

fn w1(jobs: Arc<Mutex<mpsc::Receiver<u32>>>, stop: Arc<Semaphore>, m: Arc<Mutex<u32>>) -> u32 {
    let a = jobs.lock().unwrap().recv().unwrap();
    let b = jobs.lock().unwrap().recv().unwrap();
    stop.take();
    *m.lock().unwrap() += 1;
    a + b
}

fn w2(jobs: Arc<Mutex<mpsc::Receiver<u32>>>, stop: Arc<Semaphore>, m: Arc<Mutex<u32>>) -> u32 {
    let a = jobs.lock().unwrap().recv().unwrap();
    let b = jobs.lock().unwrap().recv().unwrap();
    stop.take();
    *m.lock().unwrap() += 1;
    a + b
}

fn main() {
    let (jt, jr) = mpsc::sync_channel::<u32>(1);
    let jobs = Arc::new(Mutex::new(jr));
    let stop = Semaphore::new(0);
    let m = Arc::new(Mutex::new(0u32));

    let (s1, m1) = (Arc::clone(&stop), Arc::clone(&m));
    let p = thread::spawn(move || producer(jt, s1, m1));
    let (j1, s2, m2) = (Arc::clone(&jobs), Arc::clone(&stop), Arc::clone(&m));
    let w1 = thread::spawn(move || w1(j1, s2, m2));
    let (j2, s3, m3) = (Arc::clone(&jobs), Arc::clone(&stop), Arc::clone(&m));
    let w2 = thread::spawn(move || w2(j2, s3, m3));

    let r1 = w1.join().unwrap();
    let r2 = w2.join().unwrap();
    p.join().unwrap();
    println!("DONE sum={}", r1 + r2);
}
