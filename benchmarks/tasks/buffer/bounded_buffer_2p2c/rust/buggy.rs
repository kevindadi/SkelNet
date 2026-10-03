//! Defect program for buffer/bounded_buffer_2p2c.
//!
//! Same producers, consumers, buffer, and item values as fixed.rs. The defect
//! is that both sides share a single condition variable and wake it with
//! `notify_one`, so a wake-up meant for one side can be consumed by the other
//! and a waiter can be left asleep. New program (SkelNet R7b).

use std::collections::VecDeque;
use std::sync::{Arc, Condvar, Mutex};
use std::thread;

type Buffer = Arc<(Mutex<VecDeque<i32>>, Condvar)>;

fn p1(buf: Buffer, value: i32) {
    let (lock, cv) = &*buf;
    let mut queue = lock.lock().unwrap();
    while queue.len() >= 1 {
        queue = cv.wait(queue).unwrap();
    }
    queue.push_back(value);
    cv.notify_one();
}

fn p2(buf: Buffer, value: i32) {
    let (lock, cv) = &*buf;
    let mut queue = lock.lock().unwrap();
    while queue.len() >= 1 {
        queue = cv.wait(queue).unwrap();
    }
    queue.push_back(value);
    cv.notify_one();
}

fn c1(buf: Buffer) -> i32 {
    let (lock, cv) = &*buf;
    let mut queue = lock.lock().unwrap();
    while queue.is_empty() {
        queue = cv.wait(queue).unwrap();
    }
    let item = queue.pop_front().unwrap();
    cv.notify_one();
    item
}

fn c2(buf: Buffer) -> i32 {
    let (lock, cv) = &*buf;
    let mut queue = lock.lock().unwrap();
    while queue.is_empty() {
        queue = cv.wait(queue).unwrap();
    }
    let item = queue.pop_front().unwrap();
    cv.notify_one();
    item
}

fn main() {
    let buf: Buffer = Arc::new((Mutex::new(VecDeque::new()), Condvar::new()));

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
