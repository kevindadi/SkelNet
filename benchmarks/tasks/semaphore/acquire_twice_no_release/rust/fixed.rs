use std::sync::mpsc;
struct Sem { n: std::sync::Mutex<u32>, cv: std::sync::Condvar }
impl Sem { fn new(n:u32)->Self{Self{n:std::sync::Mutex::new(n),cv:std::sync::Condvar::new()}}
  fn acq(&self){ let mut c=self.n.lock().unwrap(); while *c==0 { c=self.cv.wait(c).unwrap(); } *c-=1; }
  fn rel(&self){ *self.n.lock().unwrap()+=1; self.cv.notify_one(); } }
fn main() {
    let s=std::sync::Arc::new(Sem::new(1));
    let s1=std::sync::Arc::clone(&s);
    let w1=std::thread::spawn(move||{ s1.acq(); s1.rel(); s1.acq(); s1.rel(); });
    let s2=std::sync::Arc::clone(&s);
    let w2=std::thread::spawn(move||{ s2.acq(); s2.rel(); });
    w1.join().unwrap(); w2.join().unwrap();
    println!("DONE done=1");
}
