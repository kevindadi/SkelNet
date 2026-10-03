//! Reference program for buffer/sensor_tray.
//!
//! Two sensors each place one reading (values 5 and 9) into a single-slot tray;
//! two recorders each pick one reading up. Sensors block on `tray_empty` while
//! the tray is occupied and recorders block on `tray_full` while it is empty,
//! each signalling the opposite condition after it changes the tray. The
//! printed value is the sum of the two readings the recorders actually picked
//! up.

use std::collections::VecDeque;
use std::sync::{Arc, Condvar, Mutex};
use std::thread;

type Tray = Arc<(Mutex<VecDeque<i32>>, Condvar, Condvar)>;

fn sensor_a(tray: Tray, value: i32) {
    let (lock, tray_empty, tray_full) = &*tray;
    let mut readings = lock.lock().unwrap();
    while readings.len() >= 1 {
        readings = tray_empty.wait(readings).unwrap();
    }
    readings.push_back(value);
    tray_full.notify_one();
}

fn sensor_b(tray: Tray, value: i32) {
    let (lock, tray_empty, tray_full) = &*tray;
    let mut readings = lock.lock().unwrap();
    while readings.len() >= 1 {
        readings = tray_empty.wait(readings).unwrap();
    }
    readings.push_back(value);
    tray_full.notify_one();
}

fn recorder_a(tray: Tray) -> i32 {
    let (lock, tray_empty, tray_full) = &*tray;
    let mut readings = lock.lock().unwrap();
    while readings.is_empty() {
        readings = tray_full.wait(readings).unwrap();
    }
    let reading = readings.pop_front().unwrap();
    tray_empty.notify_one();
    reading
}

fn recorder_b(tray: Tray) -> i32 {
    let (lock, tray_empty, tray_full) = &*tray;
    let mut readings = lock.lock().unwrap();
    while readings.is_empty() {
        readings = tray_full.wait(readings).unwrap();
    }
    let reading = readings.pop_front().unwrap();
    tray_empty.notify_one();
    reading
}

fn main() {
    let tray: Tray = Arc::new((Mutex::new(VecDeque::new()), Condvar::new(), Condvar::new()));

    let t1 = Arc::clone(&tray);
    let sensor_a = thread::spawn(move || sensor_a(t1, 5));
    let t2 = Arc::clone(&tray);
    let sensor_b = thread::spawn(move || sensor_b(t2, 9));
    let t3 = Arc::clone(&tray);
    let recorder_a = thread::spawn(move || recorder_a(t3));
    let t4 = Arc::clone(&tray);
    let recorder_b = thread::spawn(move || recorder_b(t4));

    sensor_a.join().unwrap();
    sensor_b.join().unwrap();
    let first = recorder_a.join().unwrap();
    let second = recorder_b.join().unwrap();
    println!("DONE total={}", first + second);
}
