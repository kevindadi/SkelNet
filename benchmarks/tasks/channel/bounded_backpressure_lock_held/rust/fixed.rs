use std::sync::{Arc, Condvar, Mutex, mpsc};
use std::thread;

fn main() {
    let (tx,rx)=mpsc::sync_channel::<i32>(1);
    let s=thread::spawn(move||{ tx.send(1).unwrap(); tx.send(2).unwrap(); });
    let r=thread::spawn(move||{ rx.recv().unwrap(); rx.recv().unwrap(); });
    s.join().unwrap(); r.join().unwrap();
    println!("DONE done=1");
}
