"""Regenerate the committed ``tiny/`` fixture (round-8 T1).

The success/failure matrices below are hand-authored; ``EXPECTED.md`` records
the hand-derived statistics.  Run from the repository root::

    python python/tests/fixtures/round08/tiny/make_tiny.py
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent

_spec = importlib.util.spec_from_file_location("r8synth", HERE.parent / "synth.py")
synth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(synth)

MODELS = [synth.MODELS[2], synth.MODELS[0]]  # DeepSeek Flash, GPT 6 Luna
GROUPS = [
    {"label": "G0", "arm": "G0", "kind": "g0"},
    {"label": "STATIC", "arm": "STATIC", "kind": "baseline"},
    {"label": "SKEL", "arm": "SKEL", "kind": "skel"},
]
TASKS = [
    {"task": "lock-order/abba_2lock", "tier": "L1", "origin": "classic"},
    {"task": "condvar/lost_wakeup", "tier": "L2", "origin": "classic"},
    {"task": "semaphore/permits", "tier": "L3", "origin": "disguised"},
]

# Outcome codes: T ok, F fail, S skipped, E error, N functional_ok null.
# {arm: {model_slug: {task: [rep0, rep1, rep2]}}}
MATRIX = {
    "G0": {
        "deepseek": {"lock-order/abba_2lock": ["T", "F", "T"],
                     "condvar/lost_wakeup": ["S", "F", "T"],
                     "semaphore/permits": ["T", "F", "F"]},
        "gpt": {"lock-order/abba_2lock": ["F", "T", "T"],
                "condvar/lost_wakeup": ["T", "F", "F"],
                "semaphore/permits": ["T", "F", "T"]},
    },
    "STATIC": {
        "deepseek": {"lock-order/abba_2lock": ["F", "T", "T"],
                     "condvar/lost_wakeup": ["E", "F", "T"],
                     "semaphore/permits": ["F", "T", "F"]},
        "gpt": {"lock-order/abba_2lock": ["T", "T", "F"],
                "condvar/lost_wakeup": ["F", "T", "F"],
                "semaphore/permits": ["F", "T", "T"]},
    },
    "SKEL": {
        "deepseek": {"lock-order/abba_2lock": ["T", "T", "F"],
                     "condvar/lost_wakeup": ["N", "T", "T"],
                     "semaphore/permits": ["T", "T", "T"]},
        "gpt": {"lock-order/abba_2lock": ["T", "F", "T"],
                "condvar/lost_wakeup": ["T", "T", "F"],
                "semaphore/permits": ["T", "T", "F"]},
    },
}

# One failure category per failing cell, in reading order (skipped/error cells
# are simply not consumed).  Codes map to the D8-14 columns.
FAIL_SEQUENCE = {
    "G0": ["build", "deadl", "hang", "output", "policy", "other", "design",
           "monitor"],
    "STATIC": ["output", "deadl", "build", "hang", "monitor", "other",
               "policy", "design"],
    "SKEL": ["deadl", "output", "design", "hang"],
}

NO_CONCURRENCY = {("deepseek", "SKEL", "lock-order/abba_2lock", 0)}


def _plan() -> dict:
    plan: dict = {}
    counters = {}
    for group in GROUPS:
        label = group["label"]
        arm = group["arm"]
        counters[label] = 0
        for model in MODELS:
            matrix = MATRIX[label][model["slug"]]
            for task in TASKS:
                for rep, code in enumerate(matrix[task["task"]]):
                    key = f"{model['slug']}/{label}/{task['task']}/{rep}"
                    if code == "T":
                        cell = {"status": "ok", "ok": True, "fail": None,
                                "accepted": True, "calls": 2, "skel_calls": 1}
                    elif code == "F":
                        cat = FAIL_SEQUENCE[arm][counters[label]]
                        counters[label] += 1
                        cell = {"status": "ok", "ok": False, "fail": cat,
                                "accepted": False, "calls": 1}
                    elif code == "S":
                        cell = {"status": "skipped", "ok": False, "fail": None,
                                "accepted": False, "calls": 0}
                    elif code == "E":
                        cell = {"status": "error", "ok": False, "fail": None,
                                "error": "cell_budget_exhausted",
                                "accepted": False, "calls": 1}
                    else:  # N
                        cell = {"status": "ok", "ok": None, "fail": None,
                                "accepted": False, "calls": 2, "skel_calls": 1}
                    if (model["slug"], label, task["task"], rep) in NO_CONCURRENCY:
                        cell["features"] = ["no_concurrency"]
                        cell["old_o3"] = True
                    plan[key] = cell
    return plan


def make() -> list[Path]:
    spec = {
        "seed": 20260928,
        "reps": 3,
        "call_budget": 5,
        "models": MODELS,
        "groups": GROUPS,
        "tasks": TASKS,
        "plan": _plan(),
    }
    return synth.make_runs(HERE, spec)


if __name__ == "__main__":
    runs = make()
    print(f"wrote {len(runs)} runs under {HERE}")
