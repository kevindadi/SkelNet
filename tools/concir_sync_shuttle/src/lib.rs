//! A Shuttle-backed stand-in for `concir_sync`.
//!
//! Same public API as `runtime/concir_sync`, but the semaphore is built from
//! `shuttle::sync` so a generated program can be explored under Shuttle's
//! scheduler. `set_recorder` is a no-op here: the Shuttle build never installs
//! the `cir_trace` recorder.

use shuttle::sync::{Arc, Condvar, Mutex};
use std::sync::OnceLock;

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

    /// Block until one permit is available, consume it, and do not return it.
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
    /// extra); releasing by dropping the permit is equally valid.
    pub fn release(self) {}

    /// Consume the permit without releasing it.
    pub fn forget(self) {
        std::mem::forget(self);
    }
}

impl<'a> Drop for Permit<'a> {
    fn drop(&mut self) {
        self.sem.release_one();
    }
}
