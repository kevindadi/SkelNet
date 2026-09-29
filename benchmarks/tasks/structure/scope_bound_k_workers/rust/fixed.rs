//! Match gold.skel: three scoped workers each hold the single permit for one work unit.
//! Spawn/join expresses the scope; joined work totals require no extra mutex.
use concir_sync::Semaphore;
use std::sync::Arc;
use std::thread;

fn w1(s: Arc<Semaphore>) -> u32 {
    let permit = s.acquire();
    let mut completed = 0;
    completed += 1;
    drop(permit);
    completed
}

fn w2(s: Arc<Semaphore>) -> u32 {
    let permit = s.acquire();
    let mut completed = 0;
    completed += 1;
    drop(permit);
    completed
}

fn w3(s: Arc<Semaphore>) -> u32 {
    let permit = s.acquire();
    let mut completed = 0;
    completed += 1;
    drop(permit);
    completed
}

fn main() {
    let s = Semaphore::new(1);
    let s1 = Arc::clone(&s);
    let w1 = thread::spawn(move || w1(s1));
    let s2 = Arc::clone(&s);
    let w2 = thread::spawn(move || w2(s2));
    let s3 = Arc::clone(&s);
    let w3 = thread::spawn(move || w3(s3));
    let completed = w1.join().unwrap() + w2.join().unwrap() + w3.join().unwrap();
    println!("DONE completed={}", completed);
}
