"""T7: artificial mutants of a reference program.

Three families, each expected to fail O2 or O4:

* ``print_only``  — ``main`` only prints the expected terminal line;
* ``serialized``  — ``thread::spawn`` runs the closure immediately (no concurrency);
* ``global_lock`` — one global mutex taken at the top of every spawned closure.

Programs that cannot be rewritten reliably (e.g. ``thread::scope``) are reported
``mutant_unsupported`` rather than approximated.
"""

from __future__ import annotations

import re

_SPAWN_RE = re.compile(r"\bthread\s*::\s*spawn\s*\(")

_SERIAL_HELPER = """

// skelnet mutant helper: run the spawned closure immediately, keep join().
mod __skelnet_serial {
    pub struct Handle<T>(pub Option<T>);
    impl<T> Handle<T> {
        pub fn join(self) -> Result<T, Box<dyn std::any::Any + Send>> {
            Ok(self.0.unwrap())
        }
    }
}
fn __skelnet_serial_spawn<F, T>(f: F) -> __skelnet_serial::Handle<T>
where
    F: FnOnce() -> T,
{
    __skelnet_serial::Handle(Some(f()))
}
"""

_GLOBAL_LOCK = (
    "\nstatic __SKELNET_GLOBAL_LOCK: std::sync::Mutex<()> = "
    "std::sync::Mutex::new(());\n"
)


def _print_only(terminal: str | None) -> tuple[str | None, str | None]:
    if not terminal:
        return None, "no terminal line to print"
    escaped = terminal.replace("\\", "\\\\").replace('"', '\\"')
    src = f'fn main() {{\n    println!("{escaped}");\n}}\n'
    return src, None


def _serialized(src: str) -> tuple[str | None, str | None]:
    if "thread::scope" in src or "thread :: scope" in src:
        return None, "thread::scope"
    if not _SPAWN_RE.search(src):
        return None, "no thread::spawn"
    out = _SPAWN_RE.sub("__skelnet_serial_spawn(", src)
    return out + _SERIAL_HELPER, None


_CLOSURE_HEAD_RE = re.compile(r"\|\s*[^|]*\|")


def _match_paren(src: str, open_index: int) -> int | None:
    depth = 0
    i = open_index
    in_str = False
    esc = False
    while i < len(src):
        c = src[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _global_lock(src: str) -> tuple[str | None, str | None]:
    if "thread::scope" in src or "thread :: scope" in src:
        return None, "thread::scope"
    if not _SPAWN_RE.search(src):
        return None, "no thread::spawn"
    guard = "let _skelnet_guard = __SKELNET_GLOBAL_LOCK.lock().unwrap(); "
    pieces: list[str] = []
    pos = 0
    replaced = 0
    while True:
        match = _SPAWN_RE.search(src, pos)
        if match is None:
            break
        open_paren = match.end() - 1
        close_paren = _match_paren(src, open_paren)
        if close_paren is None:
            return None, "unbalanced thread::spawn"
        head = _CLOSURE_HEAD_RE.search(src, match.end())
        if head is None or head.end() > close_paren:
            return None, "no closure in thread::spawn"
        pieces.append(src[pos:head.end()])
        pieces.append("{ " + guard)
        pieces.append(src[head.end():close_paren])
        pieces.append("}")
        pos = close_paren
        replaced += 1
    if not replaced:
        return None, "no thread::spawn"
    pieces.append(src[pos:])
    return "".join(pieces) + _GLOBAL_LOCK, None


def generate_mutants(fixed_src: str, *, terminal: str | None = None) -> dict[str, dict]:
    """Return ``{name: {"source": str|None, "reason": str|None}}``."""
    result: dict[str, dict] = {}
    for name, fn in (("print_only", lambda s: _print_only(terminal)),
                     ("serialized", _serialized),
                     ("global_lock", _global_lock)):
        source, reason = fn(fixed_src)
        result[name] = {"source": source, "reason": reason}
    return result
