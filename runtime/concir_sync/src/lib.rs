//! A standard-library-only counting semaphore for generated Rust.
//!
//! The crate carries no tracing code of its own. `acquire`/`post`/`take`
//! invoke a recorder callback if one is installed by the generated
//! `cir_trace` runtime, so the same crate works with or without
//! instrumentation.

use std::sync::{Arc, Condvar, Mutex, OnceLock};

type Recorder = fn(&str, &str);

static RECORDER: OnceLock<Recorder> = OnceLock::new();

/// Install the recorder used for `sem_acquire`/`sem_release` events.
pub fn set_recorder(recorder: Recorder) {
    let _ = RECORDER.set(recorder);
}

fn emit(op: &str, resource: &str) {
    if let Some(recorder) = RECORDER.get() {
        recorder(op, resource);
    }
}

pub struct Semaphore {
    permits: Mutex<i64>,
    cv: Condvar,
    name: &'static str,
}

pub struct Permit<'a> {
    sem: &'a Semaphore,
}

impl Semaphore {
    pub fn new(n: i64) -> Arc<Self> {
        Self::new_named("semaphore", n)
    }

    pub fn new_named(name: &'static str, n: i64) -> Arc<Self> {
        Arc::new(Semaphore {
            permits: Mutex::new(n),
            cv: Condvar::new(),
            name,
        })
    }

    pub fn acquire(&self) -> Permit<'_> {
        let mut p = self.permits.lock().unwrap();
        while *p <= 0 {
            p = self.cv.wait(p).unwrap();
        }
        *p -= 1;
        emit("sem_acquire", self.name);
        Permit { sem: self }
    }

    pub fn try_acquire(&self) -> Option<Permit<'_>> {
        let mut p = self.permits.lock().unwrap();
        if *p > 0 {
            *p -= 1;
            emit("sem_acquire", self.name);
            Some(Permit { sem: self })
        } else {
            None
        }
    }

    /// Block until one permit is available, consume it, and do not return it
    /// (the P operation; `acquire().forget()`). Emits `sem_acquire`.
    pub fn take(&self) {
        self.acquire().forget();
    }

    /// Add one permit (the V operation). Emits `sem_release`.
    pub fn post(&self) {
        self.release_one();
    }

    fn release_one(&self) {
        let mut p = self.permits.lock().unwrap();
        *p += 1;
        emit("sem_release", self.name);
        self.cv.notify_one();
    }
}

impl<'a> Permit<'a> {
    /// Release explicitly and consume the permit (the drop then does nothing
    /// extra); releasing by dropping the permit is equally valid. There is no
    /// `Semaphore::release`, so a permit cannot be released twice.
    pub fn release(self) {}

    /// Consume the permit without releasing it: the permit is permanently
    /// taken (used by [`Semaphore::take`]).
    pub fn forget(self) {
        std::mem::forget(self);
    }
}

impl<'a> Drop for Permit<'a> {
    fn drop(&mut self) {
        self.sem.release_one();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex as StdMutex;

    static OPS: OnceLock<StdMutex<Vec<String>>> = OnceLock::new();

    fn rec(op: &str, resource: &str) {
        OPS.get_or_init(|| StdMutex::new(Vec::new()))
            .lock()
            .unwrap()
            .push(format!("{op}:{resource}"));
    }

    #[test]
    fn take_consumes_and_post_adds_a_permit() {
        set_recorder(rec);
        let s = Semaphore::new_named("s", 1);

        // take() (P) emits sem_acquire, consumes the only permit, never returns
        // it: the following try_acquire finds nothing.
        s.take();
        assert!(s.try_acquire().is_none());

        // post() (V) emits sem_release and adds one permit back.
        s.post();
        let p = s.try_acquire().expect("permit available after post");
        drop(p);

        // RAII acquire also emits sem_acquire; the drop emits sem_release.
        let p = s.acquire();
        drop(p);

        let ops = OPS.get().unwrap().lock().unwrap().clone();
        assert_eq!(
            ops,
            vec![
                "sem_acquire:s".to_string(), // take
                "sem_release:s".to_string(), // post
                "sem_acquire:s".to_string(), // try_acquire
                "sem_release:s".to_string(), // drop(try permit)
                "sem_acquire:s".to_string(), // acquire
                "sem_release:s".to_string(), // drop(permit)
            ]
        );
    }
}
