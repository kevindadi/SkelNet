"""T4: SKEL/CIR call budget, unverified-Rust policy and the rust_fix retry."""

import json

from skelnet import cli
from skelnet.backend import Backend, BackendResult, repo_root
from skelnet.oracle import FakeOracle
from skelnet.params import RunParams
from skelnet.pipeline import classify_rust_reply, run_cir_cell, run_skel_cell
from skelnet.providers import ScriptedProvider
from skelnet.rusttools.compile import CompileResult

from _fake_sdk import run_args
from round03_helpers import FakeTools, ns
from test_pipeline_skel import BUGGY, FIXED, RUST

CONTRACT = repo_root() / "benchmarks/tasks/lock-order/abba_2lock/contract.json"
RUST_BAD = "```rust\nfn main() { let x = 1 }\n```"
RUST_GOOD = "```rust\nfn main() { println!(\"DONE\"); }\n```"


def _compile(oks):
    seq = iter(oks)

    def fn(tools, workdir, source, **kwargs):
        ok = next(seq, True)
        if ok:
            return CompileResult(ok=True)
        return CompileResult(ok=False, errors=[
            {"level": "error", "code": "E0308", "message": "mismatched types",
             "rendered": "error[E0308]: mismatched types\n"}])
    return fn


def _run(provider, *, rounds=4, call_budget=5, compile_oks=(True,), **kwargs):
    return run_skel_cell(
        task="lock-order/abba_2lock", requirements="two workers, two locks",
        contract_path=CONTRACT, provider=provider, backend=Backend(),
        oracle=FakeOracle(True), workdir=kwargs.pop("workdir"),
        rounds=rounds, call_budget=call_budget, compile_fn=_compile(compile_oks),
        **kwargs)


# ── budget ───────────────────────────────────────────────────────────
def test_total_calls_never_exceed_budget(tmp_path):
    provider = ScriptedProvider([{"text": FIXED}] + [{"text": RUST_GOOD}] * 6)
    result = _run(provider, rounds=4, call_budget=5, compile_oks=(False,) * 5,
                  workdir=tmp_path)
    assert len(provider.calls) == 5
    assert result.extra["rust_calls"] == 4  # skeleton 1 + rust 4
    assert result.extra["rust_compiled"] is False
    assert result.rust == "fn main() { println!(\"DONE\"); }"


def test_skeleton_all_fail_uses_last_version(tmp_path):
    provider = ScriptedProvider([{"text": BUGGY}] * 4 + [{"text": RUST_GOOD}])
    result = _run(provider, rounds=4, call_budget=5, workdir=tmp_path)
    assert len(provider.calls) == 5
    assert result.extra["skel_verified"] is False
    assert result.extra["rust_compiled"] is True
    assert result.accepted is False
    assert result.rust == "fn main() { println!(\"DONE\"); }"
    assert result.oracle is not None  # the oracle still scores the final Rust


def test_compile_fail_then_fix(tmp_path):
    provider = ScriptedProvider([{"text": FIXED}, {"text": RUST_BAD},
                                 {"text": RUST_GOOD}])
    result = _run(provider, rounds=4, call_budget=5, compile_oks=(False, True),
                  workdir=tmp_path)
    assert result.accepted is True
    assert result.extra["rust_calls"] == 2
    fix = provider.calls[2]
    assert fix.stage == "rust_fix"
    assert fix.current_program == "fn main() { let x = 1 }"
    assert "skeleton abba_ok" in fix.previous_candidate
    assert "E0308" in fix.feedback
    assert len(provider.calls) == 3


def test_skip_when_unverified(tmp_path):
    provider = ScriptedProvider([{"text": BUGGY}] * 4)
    result = _run(provider, rounds=4, call_budget=5, rust_when_unverified="skip",
                  workdir=tmp_path)
    assert result.extra["rust_skipped"] == "unverified"
    assert result.rust is None and result.oracle is None
    assert len(provider.calls) == 4


def test_other_reply_keeps_previous_and_adds_format_note(tmp_path):
    from skelnet import prompts
    provider = ScriptedProvider([{"text": FIXED}, {"text": RUST_BAD},
                                 {"text": "no program here"}, {"text": RUST_GOOD}])
    result = _run(provider, rounds=4, call_budget=5, compile_oks=(False, True),
                  workdir=tmp_path)
    assert result.accepted is True
    assert result.extra["rust_attempts"][1]["reply_kind"] == "other"
    retry = provider.calls[3]
    assert retry.feedback.startswith(prompts.FORMAT_RETRY_NOTE)
    assert len(provider.calls) == 4


def test_transport_truncated_enters_rust(tmp_path):
    provider = ScriptedProvider([{"text": BUGGY},
                                 {"error": "transport_truncated"},
                                 {"text": RUST_GOOD}])
    result = _run(provider, rounds=4, call_budget=5, workdir=tmp_path)
    assert result.extra["skel_verified"] is False
    assert result.rust == "fn main() { println!(\"DONE\"); }"
    assert len(provider.calls) == 3


class _FakeBackend:
    """check ok; verify returns a fixed (outcome, complete) sequence."""

    def __init__(self, outcomes):
        self._outcomes = iter(outcomes)

    def check(self, path):
        return BackendResult("semantic", "ok", payload={"diagnostics": []})

    def verify(self, path, contract_path):
        outcome, complete = next(self._outcomes)
        return BackendResult("semantic", "ok", outcome=outcome, complete=complete,
                             payload={"properties": []})


def test_pass_but_incomplete_is_not_accepted(tmp_path):
    provider = ScriptedProvider([{"text": FIXED}, {"text": FIXED},
                                 {"text": RUST_GOOD}])
    backend = _FakeBackend([("PASS", False), ("PASS", True)])
    result = run_skel_cell(
        task="t", requirements="r", contract_path=CONTRACT, provider=provider,
        backend=backend, oracle=FakeOracle(True), workdir=tmp_path, rounds=4,
        call_budget=5, compile_fn=_compile([True]))
    # The first PASS/complete=false was not accepted; the second was.
    assert result.extra["skel_verified"] is True
    assert len(provider.calls) == 3


# ── CIR covers the same first three rules ────────────────────────────
def test_cir_budget_and_unverified(tmp_path):
    cir = (repo_root() / "benchmarks/tasks/lock-order/abba_2lock/gold.cir.json").read_text()
    provider = ScriptedProvider([{"text": "not json"}] * 4 + [{"text": RUST_GOOD}])
    result = run_cir_cell(
        task="lock-order/abba_2lock", requirements="r", contract_path=CONTRACT,
        provider=provider, backend=Backend(), oracle=FakeOracle(True),
        workdir=tmp_path, rounds=4, call_budget=5, compile_fn=_compile([True]))
    assert len(provider.calls) == 5
    assert result.extra["skel_verified"] is False
    assert result.accepted is False


# ── real path through cmd_run ────────────────────────────────────────
class _Outcome:
    def __init__(self, text):
        self.text = text
        self.usage = None
        self.requested_model = "deepseek-flash"
        self.response_model = None
        self.request_id = None
        self.transport_attempt = 1
        self.cost = None
        self.cache_hit = False
        self.finish_reason = "stop"
        self.finish_reasons = ["stop"]
        self.usage_attempts = []
        self.temperature_sent = None
        self.wall_ms = 0


class _ScriptedChat:
    def __init__(self, texts):
        self._texts = list(texts)
        self._i = 0

    def complete(self, system, user):
        text = self._texts[self._i] if self._i < len(self._texts) else ""
        self._i += 1
        return _Outcome(text)


class _CompileFailThenOk:
    """A runner that fails the first compile call, then delegates to FakeTools."""

    def __init__(self, tools):
        self.tools = tools
        self.compile_calls = 0

    def __call__(self, cmd, cwd, timeout, env):
        if "--message-format=json" in cmd:
            self.compile_calls += 1
            if self.compile_calls == 1:
                message = {"reason": "compiler-message",
                           "message": {"level": "error", "code": {"code": "E0308"},
                                       "message": "mismatched types",
                                       "rendered": "error[E0308]: mismatched types\n"}}
                return ns(101, json.dumps(message), "")
            return ns(0, "", "")
        return self.tools(cmd, cwd, timeout, env)


def test_cmd_run_skel_rust_fix_real_path(tmp_path):
    out = tmp_path / "run"
    args = run_args("SKEL", out, rounds=2, call_budget=5,
                    budget_file=str(tmp_path / "budget.json"))
    client = _ScriptedChat([FIXED, RUST_BAD, RUST_GOOD])
    tools = _CompileFailThenOk(FakeTools())
    rc = cli.cmd_run(args, client_factory=lambda spec, o: client, oracle_runner=tools)
    assert rc == 0
    result = json.loads(
        (out / "cells" / "lock-order" / "abba_2lock" / "0" / "result.json").read_text())
    assert result["skel_verified"] is True
    assert result["rust_compiled"] is True
    assert result["rust_calls"] == 2
    assert result["budget_used"]["calls"] == 3
    assert [c["stage"] for c in result["calls"]] == ["generate", "rust", "rust_fix"]


# ── M2: compiler unavailable / timeout ends the Rust stage ───────────
def _unavailable_compile(**kwargs):
    def fn(tools, workdir, source, **kw):
        return CompileResult(ok=False, **kwargs)
    return fn


def test_compile_unavailable_stops_the_rust_stage(tmp_path):
    provider = ScriptedProvider([{"text": FIXED}, {"text": RUST_GOOD},
                                 {"text": RUST_GOOD}])
    result = run_skel_cell(
        task="t", requirements="r", contract_path=CONTRACT, provider=provider,
        backend=Backend(), oracle=FakeOracle(True), workdir=tmp_path, rounds=4,
        call_budget=5, compile_fn=_unavailable_compile(unavailable="cargo missing"))
    assert len(provider.calls) == 2  # skeleton + one rust call, no retry
    assert result.extra["rust_compiled"] is None
    assert result.extra["rust_attempts"][0]["compile"] == "unavailable"
    assert result.error == "compile_unavailable"
    assert result.oracle is not None


def test_compile_timeout_stops_the_rust_stage(tmp_path):
    provider = ScriptedProvider([{"text": FIXED}, {"text": RUST_GOOD},
                                 {"text": RUST_GOOD}])
    result = run_skel_cell(
        task="t", requirements="r", contract_path=CONTRACT, provider=provider,
        backend=Backend(), oracle=FakeOracle(True), workdir=tmp_path, rounds=4,
        call_budget=5, compile_fn=_unavailable_compile(timed_out=True))
    assert len(provider.calls) == 2
    assert result.extra["rust_compiled"] is None
    assert result.extra["rust_attempts"][0]["compile"] == "timeout"
    assert result.error == "compile_timeout"


# ── M5: empty skeleton replies do not use the Rust format note ───────
def test_empty_skel_reply_gets_check_feedback(tmp_path):
    from skelnet import prompts
    provider = ScriptedProvider([{"text": ""}, {"text": FIXED},
                                 {"text": RUST_GOOD}])
    result = _run(provider, rounds=3, call_budget=5, workdir=tmp_path)
    second = provider.calls[1]
    assert prompts.FORMAT_RETRY_NOTE not in (second.feedback or "")
    assert "```rust" not in (second.feedback or "")
    assert result.history[0]["stage"] == "check"


def test_empty_skel_reply_keeps_last_nonempty(tmp_path):
    provider = ScriptedProvider([{"text": BUGGY}, {"text": ""}, {"text": ""},
                                 {"text": RUST_GOOD}])
    result = _run(provider, rounds=3, call_budget=5, workdir=tmp_path)
    rust_call = provider.calls[3]
    assert "skeleton abba_bug" in (rust_call.previous_candidate or "")
    assert result.extra["skel_status"] == "FAIL"


def test_empty_cir_reply_gets_check_feedback(tmp_path):
    from skelnet import prompts
    cir = (repo_root() / "benchmarks/tasks/lock-order/abba_2lock"
           / "gold.cir.json").read_text()
    provider = ScriptedProvider([{"text": ""}, {"text": cir}, {"text": RUST_GOOD}])
    result = run_cir_cell(
        task="t", requirements="r", contract_path=CONTRACT, provider=provider,
        backend=Backend(), oracle=FakeOracle(True), workdir=tmp_path, rounds=3,
        call_budget=5, compile_fn=_compile([True]))
    assert prompts.FORMAT_RETRY_NOTE not in (provider.calls[1].feedback or "")
    assert "```rust" not in (provider.calls[1].feedback or "")
    assert result.history[0]["stage"] == "verify"


# ── M3/M4: reply classification and format retry on the real path ────
class _RecordingChat(_ScriptedChat):
    def __init__(self, texts):
        super().__init__(texts)
        self.users: list[str] = []

    def complete(self, system, user):
        self.users.append(user)
        return super().complete(system, user)


SKEL_BLOCK = "```skel\nskeleton x;\nfn main() { }\n```"


def test_cmd_run_skel_block_reply_is_other(tmp_path):
    out = tmp_path / "run"
    args = run_args("SKEL", out, rounds=1, call_budget=5,
                    budget_file=str(tmp_path / "budget.json"))
    client = _RecordingChat([FIXED, SKEL_BLOCK, RUST_GOOD])
    tools = FakeTools()
    assert cli.cmd_run(args, client_factory=lambda s, o: client,
                       oracle_runner=tools) == 0
    result = json.loads(
        (out / "cells" / "lock-order" / "abba_2lock" / "0" / "result.json").read_text())
    assert result["rust_attempts"][0]["reply_kind"] == "other"
    assert result["rust_attempts"][1]["reply_kind"] == "program"
    assert [c["stage"] for c in result["calls"]] == ["generate", "rust", "rust"]


def test_cmd_run_skel_format_retry_carries_note(tmp_path):
    from skelnet import prompts
    out = tmp_path / "run"
    args = run_args("SKEL", out, rounds=1, call_budget=5,
                    budget_file=str(tmp_path / "budget.json"))
    client = _RecordingChat([FIXED, "sorry, no code", RUST_GOOD])
    tools = FakeTools()
    assert cli.cmd_run(args, client_factory=lambda s, o: client,
                       oracle_runner=tools) == 0
    result = json.loads(
        (out / "cells" / "lock-order" / "abba_2lock" / "0" / "result.json").read_text())
    assert prompts.FORMAT_RETRY_NOTE in client.users[2]
    assert client.users[2] != client.users[1]
    assert [c["stage"] for c in result["calls"]] == ["generate", "rust", "rust"]


# ── M9: CIR real path through cmd_run ────────────────────────────────
def _partial_cir() -> str:
    program = json.loads(
        (repo_root() / "benchmarks/tasks/lock-order/abba_2lock"
         / "gold.cir.json").read_text())
    for module in program["modules"]:
        for fn in module["functions"]:
            if fn["name"] == "t2":
                fn["body"] = [s for s in fn["body"] if s.get("resource") != "main::b"]
    return json.dumps(program)


def test_cmd_run_cir_real_path(tmp_path):
    gold = (repo_root() / "benchmarks/tasks/lock-order/abba_2lock"
            / "gold.cir.json").read_text()
    out = tmp_path / "run"
    args = run_args("CIR", out, rounds=2, call_budget=5,
                    budget_file=str(tmp_path / "budget.json"))
    client = _RecordingChat([_partial_cir(), gold, RUST_BAD, RUST_GOOD])
    tools = _CompileFailThenOk(FakeTools())
    assert cli.cmd_run(args, client_factory=lambda s, o: client,
                       oracle_runner=tools) == 0
    result = json.loads(
        (out / "cells" / "lock-order" / "abba_2lock" / "0" / "result.json").read_text())
    assert result["skel_verified"] is True
    assert result["rust_compiled"] is True
    assert [a["stage"] for a in result["rust_attempts"]] == ["rust", "rust_fix"]
    assert result["budget_used"]["calls"] == 4
    assert [c["stage"] for c in result["calls"]] == [
        "generate", "feedback", "rust", "rust_fix"]
    assert '"reqs"' in client.users[1] and '"R2"' in client.users[1]  # D5-4 reqs
    assert "<concir>" in client.users[3]  # the rust_fix prompt carries the design
