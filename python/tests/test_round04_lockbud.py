"""T3: lockbud bug_kind classification, toolchain override, unavailable path."""

from pathlib import Path

from skelnet.rusttools.lockbud import (LOCKBUD_TOOLCHAIN, parse_bug_kinds,
                                       run_lockbud)
from skelnet.rusttools.runner import ToolRunner

from round03_helpers import ns
from round04_helpers import lockbud_tools

_FIXTURE = Path(__file__).parent / "fixtures" / "round03" / "abba_2lock" / "rust"


def test_summary_conflictlock_is_not_a_finding():
    text = "bug_level_stat: deadlock: 0, conflictlock: 0, condvardeadlock: 0\n"
    assert parse_bug_kinds(text) == []


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
    # lockbud cc78cb7 runs its deadlock detector on both programs and emits no
    # bug_kind JSON for this fixture (same for a same-thread double lock).
    assert buggy_result.unavailable is None, buggy_result.unavailable
    assert fixed_result.unavailable is None, fixed_result.unavailable
    assert buggy_result.timed_out is False and fixed_result.timed_out is False
    for hit in [*buggy_result.hits, *fixed_result.hits]:
        assert isinstance(hit.bug_kind, str) and hit.bug_kind
