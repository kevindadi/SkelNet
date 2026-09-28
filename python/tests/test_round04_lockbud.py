"""T3: lockbud bug_kind classification, toolchain override, unavailable path."""

import json
import re
from pathlib import Path

from skelnet.rusttools.lockbud import (LOCKBUD_TOOLCHAIN, parse_bug_kinds,
                                       render_lockbud_section, run_lockbud)
from skelnet.rusttools.runner import ToolRunner

from round03_helpers import ns
from round04_helpers import lockbud_tools

_FIXTURE = Path(__file__).parent / "fixtures" / "round03" / "abba_2lock" / "rust"
_LOCKBUD = Path(__file__).parent / "fixtures" / "round04" / "lockbud"

# One ConflictLock whose diagnosis is two edges, with log lines around it.
# The first `}` closes the first edge, not the record.
_NESTED_CONFLICT = """\
[lockbud] scanning
{
  "bug_kind": "ConflictLock",
  "possibility": "Possibly",
  "diagnosis": [
    {
      "first_lock_type": "StdMutex",
      "first_lock_span": "src/main.rs:7:28: 7:40 (#0)",
      "second_lock_type": "StdMutex",
      "second_lock_span": "src/main.rs:7:55: 7:67 (#0)",
      "callchains": []
    },
    {
      "first_lock_type": "StdMutex",
      "first_lock_span": "src/main.rs:9:28: 9:40 (#0)",
      "second_lock_type": "StdMutex",
      "second_lock_span": "src/main.rs:9:55: 9:67 (#0)",
      "callchains": []
    }
  ],
  "explanation": "opposite orders"
}
[lockbud] done
bug_level_stat: deadlock: 0, conflictlock: 1
"""


def test_summary_conflictlock_is_not_a_finding():
    text = "bug_level_stat: deadlock: 0, conflictlock: 0, condvardeadlock: 0\n"
    assert parse_bug_kinds(text) == []


def test_conflictlock_raw_keeps_both_diagnosis_edges():
    hits = parse_bug_kinds(_NESTED_CONFLICT)
    assert len(hits) == 1
    assert hits[0].bug_kind == "ConflictLock"
    record = json.loads(hits[0].raw)
    edges = record["diagnosis"]
    assert len(edges) == 2
    spans = [edges[0]["first_lock_span"], edges[0]["second_lock_span"],
             edges[1]["first_lock_span"], edges[1]["second_lock_span"]]
    assert spans == [
        "src/main.rs:7:28: 7:40 (#0)",
        "src/main.rs:7:55: 7:67 (#0)",
        "src/main.rs:9:28: 9:40 (#0)",
        "src/main.rs:9:55: 9:67 (#0)",
    ]


def test_nonzero_exit_without_records_is_lockbud_failed(tmp_path):
    def run(cmd, cwd, timeout, env):
        return ns(101, "", "note: building\nerror: could not compile lockbud_probe\n")

    binary = tmp_path / "lockbud"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    result = run_lockbud(
        ToolRunner(runner=run, toolchain="nightly-test"),
        tmp_path / "work", "fn main() {}\n", timeout=5, lockbud_bin=binary)
    assert result.unavailable.startswith("lockbud_failed:")
    assert "could not compile lockbud_probe" in result.unavailable
    assert result.hits == []
    assert not result.blocking
    text = render_lockbud_section(result)
    assert "no bug_kind records" not in text
    assert "lockbud could not analyze this program:" in text


def test_nonzero_exit_with_a_record_still_blocks(tmp_path):
    def run(cmd, cwd, timeout, env):
        return ns(101, '{"bug_kind":"ConflictLock"}\n', "error: could not compile\n")

    binary = tmp_path / "lockbud"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    result = run_lockbud(
        ToolRunner(runner=run, toolchain="nightly-test"),
        tmp_path / "work", "fn main() {}\n", timeout=5, lockbud_bin=binary)
    assert result.blocking is True
    assert result.unavailable is None
    assert [h.bug_kind for h in result.hits] == ["ConflictLock"]


def test_bug_kind_records_are_classified(tmp_path):
    blob = '{"bug_kind":"DoubleLock","fn_name":"t1"}\n' \
           'bug_level_stat: deadlock: 1, conflictlock: 0\n' \
           '{"bug_kind":"ConflictLock"}\n'
    hits = parse_bug_kinds(blob, tmp_path)
    assert [h.bug_kind for h in hits] == ["DoubleLock", "ConflictLock"]


def test_lockbud_passes_nightly_toolchain_over_runner_default(tmp_path):
    seen = {}

    def run(cmd, cwd, timeout, env):
        seen["env"] = dict(env)
        seen["argv"] = list(cmd)
        return ns(0, '{"bug_kind":"CondvarDeadlock"}',
                  "conflictlock appears in the summary only")
    binary = tmp_path / "lockbud"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    result = run_lockbud(
        ToolRunner(runner=run, toolchain="nightly-2026-09-04"),
        tmp_path / "work", "fn main() {}\n", timeout=5, lockbud_bin=binary)
    assert seen["env"]["RUSTUP_TOOLCHAIN"] == LOCKBUD_TOOLCHAIN
    assert seen["env"]["RUSTC_WRAPPER"] == str(binary)
    assert seen["env"]["LOCKBUD_FLAGS"] == "-k deadlock -l lockbud_probe"
    assert seen["env"]["LOCKBUD_LOG"] == "warn"
    assert "--offline" in seen["argv"]
    assert [h.bug_kind for h in result.hits] == ["CondvarDeadlock"]
    assert result.blocking


def test_lockbud_unavailable_without_binary(tmp_path, monkeypatch):
    monkeypatch.delenv("LOCKBUD_BIN", raising=False)
    result = run_lockbud(
        ToolRunner(runner=lambda *a: ns(0, "", ""), toolchain="nightly-test"),
        tmp_path, "fn main() {}\n", timeout=5, lockbud_bin=tmp_path / "missing")
    assert result.unavailable == "lockbud_unavailable"
    assert result.hits == []
    assert not result.blocking


@lockbud_tools
def test_real_lockbud_on_abba_fixtures(tmp_path):
    buggy = (_FIXTURE / "buggy.rs").read_text(encoding="utf-8")
    fixed = (_FIXTURE / "fixed.rs").read_text(encoding="utf-8")
    buggy_result = run_lockbud(ToolRunner(), tmp_path / "buggy", buggy, timeout=600)
    fixed_result = run_lockbud(ToolRunner(), tmp_path / "fixed", fixed, timeout=600)
    # concir_sync builds under nightly-2026-02-07 (unavailable would say otherwise).
    # This owned-Arc-by-value shape is a known miss; closure ABBA and
    # same-thread DoubleLock are asserted on fixtures/round04/lockbud/.
    assert buggy_result.unavailable is None, buggy_result.unavailable
    assert fixed_result.unavailable is None, fixed_result.unavailable
    assert buggy_result.timed_out is False and fixed_result.timed_out is False
    for hit in [*buggy_result.hits, *fixed_result.hits]:
        assert isinstance(hit.bug_kind, str) and hit.bug_kind


def _run_fixture(tmp_path, name: str):
    source = (_LOCKBUD / name).read_text(encoding="utf-8")
    return run_lockbud(ToolRunner(), tmp_path / name, source, timeout=600)


@lockbud_tools
def test_real_lockbud_abba_closure_is_conflictlock(tmp_path):
    result = _run_fixture(tmp_path, "abba_closure.rs")
    assert result.unavailable is None, result.unavailable
    assert result.timed_out is False
    kinds = [h.bug_kind for h in result.hits]
    assert "ConflictLock" in kinds, kinds
    text = render_lockbud_section(result)
    source = (_LOCKBUD / "abba_closure.rs").read_text(encoding="utf-8")
    spawn_lines = [i + 1 for i, line in enumerate(source.splitlines())
                   if "thread::spawn" in line]
    assert len(spawn_lines) == 2
    for number in spawn_lines:
        assert re.search(rf":{number}:", text), (number, text)
    # The raw record is complete JSON, so both edges survive.
    assert json.loads(result.hits[0].raw)


@lockbud_tools
def test_real_lockbud_double_lock(tmp_path):
    result = _run_fixture(tmp_path, "double_lock.rs")
    assert result.unavailable is None, result.unavailable
    assert result.timed_out is False
    kinds = [h.bug_kind for h in result.hits]
    assert "DoubleLock" in kinds, kinds


@lockbud_tools
def test_real_lockbud_owned_arc_params_is_a_known_miss(tmp_path):
    # Known miss: Arc moved by value into different callees. A hit here means
    # lockbud's behavior changed and docs/baselines.md needs an update.
    result = _run_fixture(tmp_path, "abba_owned_arc_params.rs")
    assert result.unavailable is None, result.unavailable
    assert result.timed_out is False
    assert result.hits == []
