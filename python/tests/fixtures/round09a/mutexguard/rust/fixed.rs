use std::sync::{Arc, Mutex, MutexGuard};
use std::thread;

fn bump(guard: &mut MutexGuard<'_, ()>) {
    let _value = &mut **guard;
}

fn main() {
    let a = Arc::new(Mutex::new(()));
    let b = Arc::new(Mutex::new(()));
    {
        let mut warm = a.lock().unwrap();
        bump(&mut warm);
        drop(warm);
    }
    thread::scope(|s| {
        let t1 = s.spawn(|| {
            let _ga = a.lock().unwrap();
            let _gb = b.lock().unwrap();
            21
        });
        let t2 = s.spawn(|| {
            let _ga = a.lock().unwrap();
            let _gb = b.lock().unwrap();
            21
        });
        assert_eq!(t1.join().unwrap() + t2.join().unwrap(), 42);
    });
    println!("DONE t1=1 t2=1");
}
