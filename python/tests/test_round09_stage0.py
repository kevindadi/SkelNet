"""R9-P6: every Stage-0 command parses, and the task list matches the protocol."""

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
