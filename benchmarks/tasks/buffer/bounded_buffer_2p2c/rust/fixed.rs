//! Reference program for buffer/bounded_buffer_2p2c.
//!
//! Two producers each put one item (values 1 and 2) into a one-slot buffer;
//! two consumers each take one item. Producers block on `not_full` while the
//! buffer is full and consumers block on `not_empty` while it is empty, each
//! signalling the opposite condition after it changes the buffer. The printed
//! value is the sum of the two items the consumers actually took.

use std::collections::VecDeque;
use std::sync::{Arc, Condvar, Mutex};
use std::thread;

type Buffer = Arc<(Mutex<VecDeque<i32>>, Condvar, Condvar)>;

fn p1(buf: Buffer, value: i32) {
    let (lock, not_full, not_empty) = &*buf;
    let mut queue = lock.lock().unwrap();
    while queue.len() >= 1 {
        queue = not_full.wait(queue).unwrap();
    }
    queue.push_back(value);
    not_empty.notify_one();
}

fn p2(buf: Buffer, value: i32) {
    let (lock, not_full, not_empty) = &*buf;
    let mut queue = lock.lock().unwrap();
    while queue.len() >= 1 {
        queue = not_full.wait(queue).unwrap();
    }
    queue.push_back(value);
    not_empty.notify_one();
}

fn c1(buf: Buffer) -> i32 {
    let (lock, not_full, not_empty) = &*buf;
    let mut queue = lock.lock().unwrap();
    while queue.is_empty() {
        queue = not_empty.wait(queue).unwrap();
    }
    let item = queue.pop_front().unwrap();
    not_full.notify_one();
    item
}

fn c2(buf: Buffer) -> i32 {
    let (lock, not_full, not_empty) = &*buf;
    let mut queue = lock.lock().unwrap();
    while queue.is_empty() {
        queue = not_empty.wait(queue).unwrap();
    }
    let item = queue.pop_front().unwrap();
    not_full.notify_one();
    item
}

fn main() {
    let buf: Buffer = Arc::new((Mutex::new(VecDeque::new()), Condvar::new(), Condvar::new()));

    let b1 = Arc::clone(&buf);
    let p1 = thread::spawn(move || p1(b1, 1));
    let b2 = Arc::clone(&buf);
    let p2 = thread::spawn(move || p2(b2, 2));
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
