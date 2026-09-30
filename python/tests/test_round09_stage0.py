"""R9-P6: every Stage-0 command parses, and the task list matches the protocol."""

import fnmatch
import json
import shlex
from pathlib import Path

import pytest

from skelnet import cli

REPO = Path(__file__).resolve().parents[2]
COMMANDS = REPO / "experiments" / "stage0" / "COMMANDS.md"
PROTOCOL = REPO / "experiments" / "protocol.json"
TEMPLATE = REPO / "experiments" / "stage0" / "budget.template.json"


def _code_lines():
    text = COMMANDS.read_text(encoding="utf-8")
    lines = []
    in_block = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_block = not in_block
            continue
        if not in_block:
            continue
        if "python -m skelnet" in line or line.strip().startswith("TASKS="):
            lines.append(line.strip())
    return lines


def _argv(line: str):
    for marker in ("|", ">"):
        if marker in line:
            line = line.split(marker, 1)[0]
    tokens = shlex.split(line)
    assert "skelnet" in tokens, line
    index = tokens.index("skelnet")
    return tokens[index + 1:]


def test_every_skelnet_command_parses():
    parser = cli.build_parser()
    commands = [line for line in _code_lines() if "python -m skelnet" in line]
    assert len(commands) >= 25
    for line in commands:
        try:
            parser.parse_args(_argv(line))
        except SystemExit as exc:  # argparse rejected the command
            pytest.fail(f"command does not parse: {line} ({exc})")


def test_task_lists_match_protocol():
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    stage0 = protocol["stages"]["0"]["tasks"]

    tasks_assignment = next(line for line in _code_lines()
                            if line.strip().startswith("TASKS="))
    value = tasks_assignment.split("=", 1)[1].strip().strip("'\"")
    assert value.split(",") == stage0

    smoke = [line for line in _code_lines()
             if "python -m skelnet" in line and "--arm DYNAMIC_M" in line]
    assert smoke
    for line in smoke:
        argv = _argv(line)
        assert argv[argv.index("--tasks") + 1] == "lock-order/abba_2lock"


def test_template_matches_protocol_ledger():
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    limits = protocol["stages"]["0"]["ledger_limits"]
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    assert template["limits"]["0"] == limits
    assert template["stages"] == {}


def _run_out_paths():
    """The ``--out`` of every ``python -m skelnet run`` command in the doc."""
    outs = []
    for line in _code_lines():
        if "python -m skelnet run" not in line:
            continue
        argv = _argv(line)
        outs.append(argv[argv.index("--out") + 1])
    return outs


def _summary_globs():
    globs = set()
    for line in _code_lines():
        if "python -m skelnet stop-check" not in line \
                and "python -m skelnet report" not in line:
            continue
        for token in _argv(line):
            if token.startswith("$ROOT/experiments/") and "*" in token:
                globs.add(token)
    return globs


def _relative(path: str) -> str:
    """Drop the ``$ROOT/`` prefix so globs and outs share one namespace."""
    return path[len("$ROOT/"):] if path.startswith("$ROOT/") else path


def test_summary_glob_excludes_smoke_and_runs_are_unique():
    outs = _run_out_paths()
    # Every run writes under $ROOT/experiments (D9c-10).
    assert all(path.startswith("$ROOT/experiments/") for path in outs)
    smoke = [path for path in outs if "smoke" in path]
    runs = [path for path in outs if "smoke" not in path]
    assert len(smoke) == 2
    assert len(runs) == 28
    assert all(path.startswith("$ROOT/experiments/stage0-smoke/") for path in smoke)
    assert all(path.startswith("$ROOT/experiments/stage0/") for path in runs)

    globs = _summary_globs()
    assert globs == {"$ROOT/experiments/stage0/*-*/"}
    matched = set()
    for pattern in globs:
        for path in outs:
            if fnmatch.fnmatch(_relative(path) + "/", _relative(pattern)):
                matched.add(path)
    # The step-5 glob covers exactly the 28 step-4 runs, never the smoke runs.
    assert matched == set(runs)
    assert not (matched & set(smoke))

    # No duplicated (model, arm) among the step-4 runs (a duplicate cell makes
    # stop-check / report exit 2).
    def key(path):
        model, _, arm = path.rstrip("/").split("/")[-1].partition("-")
        return (model, arm)

    keys = [key(path) for path in runs]
    assert len(keys) == len(set(keys))
