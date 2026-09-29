"""Regenerate ``fp_check/FP_CHECK.json`` and ``probe/PROBE.json``.

Both files are produced by the *real* command entries with only the outermost
subprocess runner (fp-check) and the SDK client (probe) replaced by fakes, so
their structure matches what the live tools write.  Run from the repository
root::

    PYTHONPATH=python python python/tests/fixtures/round08/make_tool_fixtures.py

The fp-check input repository and the probe responses are deterministic; only
``PROBE.json``'s ``created_at`` wall-clock field varies.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
PYTHON = HERE.parents[2]

if str(PYTHON) not in sys.path:
    sys.path.insert(0, str(PYTHON))


def _write_fake_repo(root: Path) -> None:
    tasks = {
        "lock-order/abba_2lock": {
            "fixed": "fn main() { let a = 1; }\n",
            "buggy": "fn main() { let mtx_c = 1; }\n",
        },
        "semaphore/permits": {
            "fixed": "fn main() { println!(\"ok\"); }\n",
            "buggy": "fn main() { let mtx_c = 0; }\n",
        },
    }
    for rel, programs in tasks.items():
        task_dir = root / "benchmarks" / "tasks" / rel
        rust = task_dir / "rust"
        rust.mkdir(parents=True, exist_ok=True)
        (task_dir / "contract.json").write_text("{}", encoding="utf-8")
        (rust / "fixed.rs").write_text(programs["fixed"], encoding="utf-8")
        (rust / "buggy1.rs").write_text(programs["buggy"], encoding="utf-8")


def _fp_runner(cmd, cwd, timeout, env):
    cmd = [str(part) for part in cmd]
    source = ""
    for base in (Path(cwd), *Path(cwd).parents):
        candidate = base / "src" / "main.rs"
        if candidate.is_file():
            source = candidate.read_text(encoding="utf-8")
            break
    flagged = "mtx_c" in source

    def ns(code, out="", err=""):
        return SimpleNamespace(returncode=code, stdout=out, stderr=err)

    if "clippy" in cmd:
        if flagged:
            payload = {"reason": "compiler-message", "message": {
                "level": "warning", "message": "Mutex<bool>",
                "code": {"code": "clippy::mutex_atomic"},
                "rendered": "warning: Mutex<bool>\n"}}
            return ns(0, json.dumps(payload) + "\n")
        return ns(0, "")
    if env.get("RUSTC_WRAPPER"):
        if flagged:
            return ns(0, '{"bug_kind": "ConflictLock"}\n',
                      "bug_level_stat: conflictlock: 1\n")
        return ns(0, "bug_level_stat: conflictlock: 0\n")
    return ns(0, "")


def make_fp_check() -> Path:
    from skelnet import cli, tools_cli
    from skelnet.rusttools import runner as runner_mod

    with tempfile.TemporaryDirectory(prefix="r8-fp-repo-") as tmp:
        root = Path(tmp) / "repo"
        _write_fake_repo(root)
        binary = Path(tmp) / "lockbud"
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        original_root = tools_cli.repo_root
        original_runner = runner_mod.default_runner
        tools_cli.repo_root = lambda: root
        runner_mod.default_runner = _fp_runner
        import os
        os.environ["LOCKBUD_BIN"] = str(binary)
        out = Path(tmp) / "fp"
        try:
            rc = cli.main(["tools", "fp-check", "--tasks", "all",
                           "--out", str(out)])
        finally:
            tools_cli.repo_root = original_root
            runner_mod.default_runner = original_runner
        assert rc == 0
        document = json.loads((out / "FP_CHECK.json").read_text(encoding="utf-8"))
    target = HERE / "fp_check" / "FP_CHECK.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return target


class _ProbeClient:
    def __init__(self, model_id: str, seed_ok: bool = False) -> None:
        self.model_id = model_id
        self.seed_ok = seed_ok

    def set_cell(self, *_args) -> None:
        return None

    def complete(self, _system, _user):
        usage = {
            "input_tokens": 24,
            "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
            "output_tokens": 8,
            "output_tokens_details": {"reasoning_tokens": 3},
            "total_tokens": 32,
        }
        return SimpleNamespace(
            text="OK", usage=usage, response_model=self.model_id,
            finish_reason="stop", seed=(7 if self.seed_ok else None),
            reasoning_content=None,
            requested_model=self.model_id, transport_attempt=1)


def make_probe() -> Path:
    from skelnet import models_probe

    def factory(spec, _params):
        return _ProbeClient(spec.model_id, seed_ok=spec.supports_seed)

    out = HERE / "probe"
    models_probe.probe_run(out, client_factory=factory)
    return out / "PROBE.json"


if __name__ == "__main__":
    print(make_fp_check())
    print(make_probe())
