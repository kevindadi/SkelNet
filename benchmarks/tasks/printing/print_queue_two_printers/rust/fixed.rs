//! Reference program for printing/print_queue_two_printers.
//!
//! A spooler queues four print jobs (1, 2, 3, 4 sheets) into a capacity-one
//! print queue and then signals shutdown by posting one `halt` permit for each
//! of the two printers. Both printers drain the shared queue, take two jobs
//! each, then take one shutdown permit and exit. A shared mutex `ledger`
//! protects the `printed` counter. Because the spooler posts as many permits as
//! there are printers, both printers stop and the terminal line is the sum of
//! the sheets the printers actually took, not a constant.

use concir_sync::Semaphore;
use std::sync::{mpsc, Arc, Mutex};
use std::thread;

fn spooler(queue: mpsc::SyncSender<u32>, halt: Arc<Semaphore>, ledger: Arc<Mutex<u32>>) {
    queue.send(1).unwrap();
    queue.send(2).unwrap();
    queue.send(3).unwrap();
    queue.send(4).unwrap();
    halt.post();
    halt.post();
    *ledger.lock().unwrap() += 1;
}

fn printer1(
    queue: Arc<Mutex<mpsc::Receiver<u32>>>,
    halt: Arc<Semaphore>,
    ledger: Arc<Mutex<u32>>,
) -> u32 {
    let a = queue.lock().unwrap().recv().unwrap();
    let b = queue.lock().unwrap().recv().unwrap();
    halt.take();
    *ledger.lock().unwrap() += 1;
    a + b
}

fn printer2(
    queue: Arc<Mutex<mpsc::Receiver<u32>>>,
    halt: Arc<Semaphore>,
    ledger: Arc<Mutex<u32>>,
) -> u32 {
    let a = queue.lock().unwrap().recv().unwrap();
    let b = queue.lock().unwrap().recv().unwrap();
    halt.take();
    *ledger.lock().unwrap() += 1;
    a + b
}

fn main() {
    let (qt, qr) = mpsc::sync_channel::<u32>(1);
    let queue = Arc::new(Mutex::new(qr));
    let halt = Semaphore::new(0);
    let ledger = Arc::new(Mutex::new(0u32));

    let (h1, l1) = (Arc::clone(&halt), Arc::clone(&ledger));
    let spooler = thread::spawn(move || spooler(qt, h1, l1));
    let (q1, h2, l2) = (Arc::clone(&queue), Arc::clone(&halt), Arc::clone(&ledger));
    let printer1 = thread::spawn(move || printer1(q1, h2, l2));
    let (q2, h3, l3) = (Arc::clone(&queue), Arc::clone(&halt), Arc::clone(&ledger));
    let printer2 = thread::spawn(move || printer2(q2, h3, l3));

    let p1 = printer1.join().unwrap();
    let p2 = printer2.join().unwrap();
    spooler.join().unwrap();
    println!("DONE pages={}", p1 + p2);
}
