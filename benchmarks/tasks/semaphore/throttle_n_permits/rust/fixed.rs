//! Reference program for semaphore/throttle_n_permits.
//!
//! Matches gold.skel: semaphore `s` starts with 2 permits, and w1, w2, and
//! w3 each acquire one permit, record one finished unit, and release it.
//! No extra mutex: the counts are the workers' return values.

use concir_sync::Semaphore;
use std::sync::Arc;
use std::thread;

fn w1(s: Arc<Semaphore>) -> u32 {
    let permit = s.acquire();
    let mut done = 0u32;
    done += 1;
    drop(permit);
    done
}

fn w2(s: Arc<Semaphore>) -> u32 {
    let permit = s.acquire();
    let mut done = 0u32;
    done += 1;
    drop(permit);
    done
}

fn w3(s: Arc<Semaphore>) -> u32 {
    let permit = s.acquire();
    let mut done = 0u32;
    done += 1;
    drop(permit);
    done
}

fn main() {
    let s = Semaphore::new(2);
    let s1 = Arc::clone(&s);
    let w1 = thread::spawn(move || w1(s1));
    let s2 = Arc::clone(&s);
    let w2 = thread::spawn(move || w2(s2));
    let s3 = Arc::clone(&s);
    let w3 = thread::spawn(move || w3(s3));
    let n1 = w1.join().unwrap();
    let n2 = w2.join().unwrap();
    let n3 = w3.join().unwrap();
    println!("DONE w1={} w2={} w3={}", n1, n2, n3);
}
