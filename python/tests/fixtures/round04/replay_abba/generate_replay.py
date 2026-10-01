#!/usr/bin/env python3
"""Write the offline replay cache for lock-order/abba_2lock, rep 0.

Usage (from the repository root, after the oracle tools and lockbud are
installed when you want DYNAMIC entries as well)::

    python3 python/tests/fixtures/round04/replay_abba/generate_replay.py

The script calls ``cmd_run`` with a scripted client and the default model
(DeepSeek Flash) and default ``RunParams``. Replies are the ABBA program
(call 1, shared with G0) and then the fixed program. Cache files land in
this directory. Replay with::

    python -m skelnet run --arm STATIC --tasks lock-order/abba_2lock \\
        --reps 1 --replay-from python/tests/fixtures/round04/replay_abba \\
        --out /tmp/r4 --allow-missing-tools

Pass ``--dynamic`` to also record the DYNAMIC tool-feedback calls. That path
runs the real repeated-run / Shuttle / miri tools.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "python"))

from skelnet import cli  # noqa: E402

HERE = Path(__file__).resolve().parent
FIXTURE = ROOT / "python" / "tests" / "fixtures" / "round03" / "abba_2lock" / "rust"


def _fence(path: Path) -> str:
    body = path.read_text(encoding="utf-8")
    return f"```rust\n{body}\n```"


class _Scripted:
    """Call 1 is the shared generate prompt. Any later prompt is a repair.

    A cache hit on call 1 does not invoke ``complete``, so the reply cannot
    be chosen by a local counter. The generate prompt has neither
    ``<current_program>`` nor ``<tool_feedback``.
    """

    def __init__(self, buggy: str, fixed: str) -> None:
        self.buggy = buggy
        self.fixed = fixed
        self.n = 0

    def complete(self, system: str, user: str):
        self.n += 1
        if "<current_program>" in user or "<tool_feedback" in user:
            text = self.fixed
        else:
            text = self.buggy
        return SimpleNamespace(
            text=text, usage=None, requested_model="deepseek-v4-flash",
            response_model=None, request_id="replay", transport_attempt=1,
            cost=None, finish_reason="stop")


def _run(arm: str, out: Path, *, allow_missing: bool) -> int:
    buggy = _fence(FIXTURE / "buggy.rs")
    fixed = _fence(FIXTURE / "fixed.rs")
    argv = [
        "run", "--arm", arm, "--model", "DeepSeek Flash",
        "--tasks", "lock-order/abba_2lock", "--reps", "1", "--rounds", "4",
        "--hint", "h0",  # the replay tests use h0
        "--call-budget", "5", "--out", str(out),
        "--cache-dir", str(HERE),
        "--budget-file", str(out / "budget.json"),
    ]
    if allow_missing:
        argv.append("--allow-missing-tools")
    args = cli.build_parser().parse_args(argv)
    return cli.cmd_run(args, client_factory=lambda spec, o: _Scripted(buggy, fixed))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dynamic", action="store_true",
                        help="also record DYNAMIC calls (real Shuttle/miri)")
    parser.add_argument("--work", type=Path, default=Path("/tmp/r4-generate"))
    args = parser.parse_args()
    rc = _run("STATIC", args.work / "static", allow_missing=True)
    print(f"STATIC cmd_run -> {rc}")
    if rc != 0:
        return rc
    if args.dynamic:
        rc = _run("DYNAMIC", args.work / "dynamic", allow_missing=False)
        print(f"DYNAMIC cmd_run -> {rc}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
