//! MutexGuard must survive instrumentation and still emit lock/unlock events.

use std::fs;
use std::process::Command;

use concir::instrument::{wrap, RUNTIME};

fn compile_and_trace(source: &str) -> String {
    let wrapped = wrap(source).expect("wrap");
    let digest = wrapped.annotated.bytes().fold(0u64, |acc, byte| {
        acc.wrapping_mul(16777619).wrapping_add(u64::from(byte))
    });
    let root = std::env::temp_dir().join(format!("mutexguard-{digest:x}"));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(root.join("src")).unwrap();
    let manifest = env!("CARGO_MANIFEST_DIR");
    let concir_sync = std::path::Path::new(manifest)
        .join("../../runtime/concir_sync");
    fs::write(
        root.join("Cargo.toml"),
        format!(
            "[package]\nname = \"mutexguard_probe\"\nversion = \"0.1.0\"\nedition = \"2021\"\n\
             [[bin]]\nname = \"mutexguard_probe\"\npath = \"src/main.rs\"\n\
             [dependencies]\nconcir_sync = {{ path = \"{}\" }}\n",
            concir_sync.display()
        ),
    )
    .unwrap();
    fs::write(root.join("src/main.rs"), &wrapped.annotated).unwrap();
    fs::write(root.join("src/cir_trace.rs"), RUNTIME).unwrap();
    let trace = root.join("trace.jsonl");
    let status = Command::new("cargo")
        .args(["run", "--quiet", "--offline", "--manifest-path"])
        .arg(root.join("Cargo.toml"))
        .env("CIR_TRACE_OUT", &trace)
        .env_remove("RUSTC_WRAPPER")
        .env_remove("LOCKBUD_FLAGS")
        .env_remove("LOCKBUD_LOG")
        .output()
        .expect("cargo");
    assert!(
        status.status.success(),
        "compile/run failed\n--- annotated ---\n{}\n--- stderr ---\n{}",
        wrapped.annotated,
        String::from_utf8_lossy(&status.stderr)
    );
    let text = fs::read_to_string(&trace).unwrap_or_default();
    assert!(text.contains("\"op\":\"mutex_lock\""), "{text}");
    assert!(text.contains("\"op\":\"mutex_unlock\""), "{text}");
    let _ = fs::remove_dir_all(&root);
    text
}

#[test]
fn grouped_import_mutexguard_parameter() {
    compile_and_trace(
        r#"
use std::sync::{Arc, Mutex, MutexGuard};
use std::thread;
fn bump(g: &mut MutexGuard<'_, u32>) { **g += 1; }
fn main() {
    let m = Arc::new(Mutex::new(0u32));
    let m2 = Arc::clone(&m);
    let worker = thread::spawn(move || {
        let mut guard = m2.lock().unwrap();
        bump(&mut guard);
    });
    worker.join().unwrap();
}
"#,
    );
}

#[test]
fn bare_mutexguard_import() {
    compile_and_trace(
        r#"
use std::sync::Mutex;
use std::sync::MutexGuard;
fn bump(g: &mut MutexGuard<'_, u32>) { **g += 1; }
fn main() {
    let m = Mutex::new(1u32);
    let mut guard = m.lock().unwrap();
    bump(&mut guard);
    drop(guard);
}
"#,
    );
}

#[test]
fn full_path_mutexguard_in_signature() {
    compile_and_trace(
        r#"
use std::sync::Mutex;
fn bump(g: &mut std::sync::MutexGuard<'_, u32>) { **g += 1; }
fn main() {
    let m = Mutex::new(1u32);
    let mut guard = m.lock().unwrap();
    bump(&mut guard);
    drop(guard);
}
"#,
    );
}

#[test]
fn mutexguard_return_type() {
    compile_and_trace(
        r#"
use std::sync::{Mutex, MutexGuard};
fn take<'a, T>(m: &'a Mutex<T>) -> MutexGuard<'a, T> { m.lock().unwrap() }
fn main() {
    let m = Mutex::new(1u32);
    let guard = take(&m);
    drop(guard);
}
"#,
    );
}

#[test]
fn typed_guard_passed_to_condvar_wait() {
    compile_and_trace(
        r#"
use std::sync::{Arc, Condvar, Mutex, MutexGuard};
use std::thread;
fn wait_typed<'a>(cv: &'a Condvar, guard: MutexGuard<'a, bool>) -> MutexGuard<'a, bool> {
    cv.wait(guard).unwrap()
}
fn main() {
    let m = Arc::new(Mutex::new(false));
    let cv = Arc::new(Condvar::new());
    let (m2, cv2) = (Arc::clone(&m), Arc::clone(&cv));
    let guard: MutexGuard<'_, bool> = m.lock().unwrap();
    let notifier = thread::spawn(move || {
        let _held = m2.lock().unwrap();
        cv2.notify_one();
    });
    let guard = wait_typed(&cv, guard);
    drop(guard);
    notifier.join().unwrap();
}
"#,
    );
}
