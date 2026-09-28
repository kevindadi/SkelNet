"""T1/M1/M2: the shared Rust compile check, path hygiene and unavailability."""

import json
import os
import subprocess
import sys
from pathlib import Path

from skelnet.backend import repo_root
from skelnet.rusttools.compile import CompileResult, compile_rust, render_compile_errors
from skelnet.rusttools.runner import ToolRunner

from round03_helpers import cargo_only, ns


def _message(level, code, text, rendered):
    return {"reason": "compiler-message",
            "message": {"level": level, "code": {"code": code} if code else None,
                        "message": text, "rendered": rendered}}


def _recorded_output(workdir: Path) -> str:
    base = str(workdir)
    lines = [
        {"reason": "compiler-artifact", "package_id": "probe 0.1.0"},
        _message("error", "E0425", "cannot find value `x` in this scope",
                 f"error[E0425]: cannot find value `x` in this scope\n --> {base}/src/main.rs:2:5\n  |\n2 |     x;\n  |     ^ not found in this scope\n"),
        _message("warning", "unused_variables", "unused variable: `y`",
                 f"warning: unused variable: `y`\n --> {base}/src/main.rs:3:9\n  |\n3 |     let y = 1;\n  |         ^ help: if this is intentional, prefix it with an underscore\n"),
        _message("error", None, "aborting due to 1 previous error",
                 "error: aborting due to 1 previous error\n"),
        {"reason": "build-finished", "success": False},
    ]
    return "\n".join(json.dumps(line) for line in lines)


def _tools(fn):
    return ToolRunner(runner=fn, toolchain="nightly-test")


def test_parse_classify_and_relativize(tmp_path):
    output = _recorded_output(tmp_path)
    tools = _tools(lambda cmd, cwd, timeout, env: ns(101, output, ""))
    result = compile_rust(tools, tmp_path, "fn main() { x; }\n")
    assert result.ok is False
    assert len(result.errors) == 1 and len(result.warnings) == 1
    assert result.errors[0]["code"] == "E0425"
    assert result.errors[0]["level"] == "error"
    assert result.warnings[0]["code"] == "unused_variables"
    # The aborting summary is dropped.
    assert all("aborting due to" not in e["message"] for e in result.errors)
    # No absolute path anywhere in a rendered diagnostic.
    assert str(tmp_path) not in result.errors[0]["rendered"]
    assert "src/main.rs" in result.errors[0]["rendered"]


def test_invocation_is_offline_json_and_pinned(tmp_path):
    tools = _tools(lambda cmd, cwd, timeout, env: ns(0, "", ""))
    compile_rust(tools, tmp_path, "fn main() {}\n")
    record = tools.records[-1]
    assert "--offline" in record["argv"]
    assert "--message-format=json" in record["argv"]
    assert "RUSTUP_TOOLCHAIN" in record["env_keys"]


def test_unavailable_and_timeout(tmp_path):
    def boom(cmd, cwd, timeout, env):
        raise OSError("cargo not found")
    result = compile_rust(_tools(boom), tmp_path, "fn main() {}\n")
    assert result.ok is False and result.unavailable

    def slow(cmd, cwd, timeout, env):
        raise subprocess.TimeoutExpired(cmd, timeout)
    result = compile_rust(_tools(slow), tmp_path, "fn main() {}\n")
    assert result.ok is False and result.timed_out


def test_render_truncates_at_utf8_boundary():
    long = "中" * 4000  # 12000 bytes
    result = CompileResult(errors=[{"level": "error", "code": None, "message": "",
                                    "rendered": long}])
    text = render_compile_errors(result, limit_bytes=100)
    assert text.endswith("[truncated]")
    # Decoding succeeded, so no multibyte character was split.
    assert "中" in text
    assert len(text.encode("utf-8")) <= 100 + len("\n[truncated]".encode())


def test_render_preserves_order():
    result = CompileResult(errors=[{"rendered": "first"}, {"rendered": "second"}])
    assert render_compile_errors(result) == "first\nsecond"


# ── M1: absolute-path hygiene ────────────────────────────────────────
def test_relativize_workdir_repo_sysroot_and_unrelated(tmp_path, monkeypatch):
    import skelnet.rusttools.compile as compile_mod
    monkeypatch.setattr(compile_mod, "_sysroot", lambda: "/fake/sysroot")
    root = str(repo_root())
    base = str(tmp_path)
    rendered = (
        "error[E0001]: boom\n"
        f" --> {base}/src/main.rs:1:1\n"
        f"  ::: {root}/runtime/concir_sync/src/lib.rs:10:5\n"
        "  = note: see /fake/sysroot/lib/rustlib/src/rust/library/alloc/src/vec/mod.rs\n"
        " --> /opt/other/path/foo.rs:1:1\n"
    )
    output = json.dumps(_message("error", "E0001", "boom", rendered))
    tools = _tools(lambda *a: ns(101, output, ""))
    result = compile_rust(tools, tmp_path, "fn main() {}\n")
    text = result.errors[0]["rendered"]
    assert base not in text
    assert root not in text
    assert "/fake/sysroot" not in text
    assert "/opt/other" not in text
    assert "runtime/concir_sync/src/lib.rs" in text
    assert "<rust>/library/alloc/src/vec/mod.rs" in text
    assert "<abs>/foo.rs" in text


# ── M2: unavailable vs. compile failure ──────────────────────────────
def test_nonzero_without_errors_is_unavailable(tmp_path):
    output = json.dumps({"reason": "compiler-artifact", "package_id": "probe 0.1.0"})
    tools = _tools(lambda *a: ns(
        101, output, "error: failed to select a version for the requirement `x`"))
    result = compile_rust(tools, tmp_path, "fn main() {}\n")
    assert result.ok is False
    assert result.errors == []
    assert result.unavailable and "failed to select a version" in result.unavailable


# ── N1: replacement order is hash-seed independent ───────────────────
def test_relativize_order_is_hash_seed_independent():
    wd = repo_root() / "experiments/run/cells/lock-order/abba_2lock/0/compile/c3"
    code = (
        "from pathlib import Path\n"
        "from skelnet.rusttools.compile import _relativize\n"
        f"wd = Path({str(wd)!r})\n"
        "print(_relativize(f'note: see {wd}/src/main.rs', wd))\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    for seed in range(32):
        env["PYTHONHASHSEED"] = str(seed)
        out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, env=env)
        assert out.stdout.strip() == "note: see src/main.rs", (seed, out.stdout, out.stderr)


@cargo_only
def test_real_cargo_diagnostics_have_no_absolute_paths(tmp_path):
    programs = {
        "vec": 'fn main() { let _ = Vec::with_capacity("x"); }\n',
        "sem": 'fn main() { let _ = concir_sync::Semaphore::new("x"); }\n',
    }
    rendered = {}
    for name, source in programs.items():
        result = compile_rust(ToolRunner(toolchain=None), tmp_path / name, source)
        assert result.ok is False
        text = render_compile_errors(result)
        rendered[name] = text
        assert str(repo_root()) not in text, name
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("-->") or stripped.startswith(":::"):
                path = stripped.split(None, 1)[1]
                assert not path.startswith("/"), (name, line)
    # The repo path is rewritten to a relative one (not just basename-masked).
    assert "runtime/concir_sync/src/lib.rs" in rendered["sem"]


@cargo_only
def test_real_cargo_missing_semicolon(tmp_path):
    workdir = tmp_path / "bad"
    result = compile_rust(ToolRunner(toolchain=None), workdir,
                          "fn main() { let x = 1 }\n")
    assert result.ok is False
    assert result.errors
    assert str(tmp_path) not in render_compile_errors(result)


@cargo_only
def test_real_cargo_ok_cleans_target(tmp_path):
    workdir = tmp_path / "good"
    result = compile_rust(ToolRunner(toolchain=None), workdir, "fn main() {}\n")
    assert result.ok is True
    assert not (workdir / "target").exists()
