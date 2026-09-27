use std::sync::{Arc, Condvar, Mutex, mpsc};
use std::thread;

fn main() {
    let p=Arc::new((Mutex::new(false), Condvar::new()));
    let mut hs=vec![];
    for _ in 0..2 { let q=Arc::clone(&p); hs.push(thread::spawn(move||{ let (m,cv)=&*q;
        let mut g=m.lock().unwrap(); while !*g { g=cv.wait(g).unwrap(); } })); }
    let q=Arc::clone(&p); let n=thread::spawn(move||{ let (m,cv)=&*q; let mut g=m.lock().unwrap();
        *g=true; cv.notify_all(); });
    n.join().unwrap(); for h in hs { h.join().unwrap(); }
    println!("DONE waiters=0");
}
