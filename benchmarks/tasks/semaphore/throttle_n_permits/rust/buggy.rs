//! Defect program for semaphore/throttle_n_permits.
//!
//! w3 takes three permits and posts none. w1 and w2 each take one and post
//! it back. The pool starts at two, so w3's third take can never be filled
//! and a worker blocks forever. The completion-count print matches fixed.rs.
//! New program (SkelNet R7a-2).

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
    s.take();
    s.take();
    s.take();
    0
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
