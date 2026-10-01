//! Reference program for buffer/bounded_buffer_semaphores.
//!
//! Two producers each put one item (values 4 and 7) into a one-slot buffer
//! guarded by a mutex and two counting semaphores: `slots` starts with one
//! permit and `items` starts with none. A producer takes a free-slot permit
//! before it locks the buffer and posts an item after it unlocks; a consumer
//! takes an available-item permit before it locks the buffer and posts a free
//! slot after it unlocks. The printed value is the sum of the two items the
//! consumers actually took.

use concir_sync::Semaphore;
use std::collections::VecDeque;
use std::sync::{Arc, Mutex};
use std::thread;

type Buffer = Arc<(Mutex<VecDeque<i32>>, Arc<Semaphore>, Arc<Semaphore>)>;

fn p1(buf: Buffer, value: i32) {
    let (lock, slots, items) = &*buf;
    slots.take();
    let mut queue = lock.lock().unwrap();
    queue.push_back(value);
    drop(queue);
    items.post();
}

fn p2(buf: Buffer, value: i32) {
    let (lock, slots, items) = &*buf;
    slots.take();
    let mut queue = lock.lock().unwrap();
    queue.push_back(value);
    drop(queue);
    items.post();
}

fn c1(buf: Buffer) -> i32 {
    let (lock, slots, items) = &*buf;
    items.take();
    let mut queue = lock.lock().unwrap();
    let item = queue.pop_front().unwrap();
    drop(queue);
    slots.post();
    item
}

fn c2(buf: Buffer) -> i32 {
    let (lock, slots, items) = &*buf;
    items.take();
    let mut queue = lock.lock().unwrap();
    let item = queue.pop_front().unwrap();
    drop(queue);
    slots.post();
    item
}

fn main() {
    let buf: Buffer = Arc::new((
        Mutex::new(VecDeque::new()),
        Semaphore::new(1),
        Semaphore::new(0),
    ));

    let b1 = Arc::clone(&buf);
    let p1 = thread::spawn(move || p1(b1, 4));
    let b2 = Arc::clone(&buf);
    let p2 = thread::spawn(move || p2(b2, 7));
    let b3 = Arc::clone(&buf);
    let c1 = thread::spawn(move || c1(b3));
    let b4 = Arc::clone(&buf);
    let c2 = thread::spawn(move || c2(b4));

    p1.join().unwrap();
    p2.join().unwrap();
    let first = c1.join().unwrap();
    let second = c2.join().unwrap();
    println!("DONE sum={}", first + second);
}
