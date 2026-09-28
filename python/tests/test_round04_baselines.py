"""T8: baseline iteration loop, acceptance, and the real cmd_run path.

The loop tests inject a compile function and (when the case is about the
loop, not the tools) a feedback function. One test per arm goes through
``cmd_run`` with only a fake client and a source-sensitive runner: no
``oracle_factory`` and no ``feedback_tools``.
"""

import json
from pathlib import Path
from types import SimpleNamespace

from skelnet import cli
from skelnet.baselines import _Feedback, run_baseline_cell
from skelnet.oracle import FakeOracle
from skelnet.params import RunParams
from skelnet.pipeline import classify_rust_reply
from skelnet.prompts import FORMAT_RETRY_NOTE
from skelnet.providers import ScriptedProvider
from skelnet.rusttools.runner import ToolRunner
from skelnet.schema import validate_cell

from round03_helpers import DEFAULT_REPORT, DEFAULT_RESOURCES, ns

TERMINAL = "DONE t1=1 t2=1"


def _rust(body: str, marker: str = "") -> str:
    comment = f"\n// {marker}" if marker else ""
    return f"```rust\nfn main() {{ {body} }}{comment}\n```"


def _params(**kwargs):
    return RunParams(**kwargs)


def _compile(tools, workdir, source):
    ok = "NOCOMPILE" not in source
    errors = [] if ok else [{
        "level": "error", "code": "E0425", "message": "boom",
        "rendered": "error[E0425]: boom\n",
    }]
    return SimpleNamespace(ok=ok, errors=errors, warnings=[], unavailable=None)


class _GuardOracle:
    """Raises if ``evaluate`` runs before the provider has finished the loop."""

    def __init__(self, provider, min_calls: int):
        self.provider = provider
        self.min_calls = min_calls
        self.n = 0
        self.workdirs: list[Path] = []
        self.inner = FakeOracle(True)

    def evaluate(self, source, workdir, **kwargs):
        if len(self.provider.calls) < self.min_calls:
            raise RuntimeError("oracle called during the loop")
        self.n += 1
        self.workdirs.append(Path(workdir))
        return self.inner.evaluate(source, workdir, **kwargs)


class _SeqFeedback:
    def __init__(self, passed: list[bool], reason: str = "static_clean"):
        self.passed = list(passed)
        self.reason = reason
        self.dirs: list[Path] = []

    def __call__(self, source, directory):
        self.dirs.append(Path(directory))
        ok = self.passed.pop(0) if self.passed else True
        return _Feedback(
            passed=ok, reason=self.reason,
            feedback="" if ok else "tool finding",
            truncated=False,
            tools={"clippy": {"status": "pass" if ok else "fail", "category": None}},
        )


def _run(tmp_path, arm, replies, *, budget=5, feedback=None, min_calls=1,
         compile_fn=_compile):
    provider = ScriptedProvider([{"text": text} for text in replies])
    oracle = _GuardOracle(provider, min_calls)
    result = run_baseline_cell(
        arm=arm, task="lock-order/abba_2lock", requirements="do the thing",
        task_dir=tmp_path, terminal=TERMINAL, provider=provider, oracle=oracle,
        workdir=tmp_path / "cell", replicate=0, run_params=_params(call_budget=budget),
        tools=ToolRunner(runner=lambda *a, **k: ns(0, "", ""), toolchain=None),
        compile_fn=compile_fn, feedback_tools=feedback)
    return result, provider, oracle


def test_refine_accepts_when_second_reply_is_no_issues(tmp_path):
    result, provider, oracle = _run(
        tmp_path, "REFINE",
        [_rust('println!("ok");'), "NO_ISSUES"],
        min_calls=2)
    assert result.accepted is True
    assert result.extra["baseline"]["accept_reason"] == "no_issues"
    assert result.extra["baseline"]["accepted_at_call"] == 2
    assert result.rounds_used == 2
    assert result.parse_ok is True
    assert result.check_ok is True
    assert oracle.n == 1
    assert len(provider.calls) == 2
    assert provider.calls[1].stage == "review"


def test_refine_no_issues_while_uncompilable_is_other(tmp_path):
    result, provider, oracle = _run(
        tmp_path, "REFINE",
        [_rust('println!("x");', "NOCOMPILE"), "NO_ISSUES",
         _rust('println!("ok");'), "NO_ISSUES"],
        min_calls=4)
    kinds = [row["reply_kind"] for row in result.extra["baseline"]["rounds"]]
    assert kinds[1] == "other"
    assert result.accepted is True
    assert result.extra["baseline"]["accept_reason"] == "no_issues"
    assert provider.calls[1].stage == "rust_fix"
    assert oracle.n == 1


def test_static_feedback_then_fix(tmp_path):
    feedback = _SeqFeedback([False, True])
    result, provider, oracle = _run(
        tmp_path, "STATIC",
        [_rust('println!("bad");'), _rust('println!("good");')],
        feedback=feedback, min_calls=2)
    assert result.accepted is True
    assert result.extra["baseline"]["accept_reason"] == "static_clean"
    assert result.rounds_used == 2
    assert "fn main() { println!(\"good\"); }" in result.rust
    assert oracle.n == 1
    assert feedback.dirs[0].parent.name == "feedback"


def test_budget_exhausted_keeps_the_fifth_version(tmp_path):
    feedback = _SeqFeedback([False] * 5)
    replies = [_rust(f'println!("{i}");') for i in range(5)]
    result, provider, oracle = _run(
        tmp_path, "STATIC", replies, feedback=feedback, budget=5, min_calls=5)
    assert result.accepted is False
    assert result.rounds_used == 5
    assert len(provider.calls) == 5
    assert result.extra["baseline"]["final_version"] == 5
    assert result.extra["baseline"]["accept_reason"] == "budget_exhausted"
    assert 'println!("4")' in result.rust
    assert oracle.n == 1


def test_compile_failure_uses_rust_fix_then_accepts(tmp_path):
    result, provider, oracle = _run(
        tmp_path, "DYNAMIC",
        [_rust('println!("x");', "NOCOMPILE"), _rust('println!("ok");')],
        feedback=_SeqFeedback([True], reason="dynamic_pass"), min_calls=2)
    assert provider.calls[1].stage == "rust_fix"
    assert "error[E0425]" in (provider.calls[1].feedback or "")
    assert result.accepted is True
    assert result.extra["baseline"]["accept_reason"] == "dynamic_pass"
    assert result.check_ok is True
    assert oracle.n == 1


def test_format_retry_keeps_the_previous_version(tmp_path):
    feedback = _SeqFeedback([False, True])
    result, provider, oracle = _run(
        tmp_path, "STATIC",
        [_rust('println!("v1");'), "not a program", _rust('println!("v2");')],
        feedback=feedback, min_calls=3)
    assert provider.calls[2].stage == "tool_feedback"
    assert (provider.calls[2].feedback or "").startswith(FORMAT_RETRY_NOTE)
    assert result.accepted is True
    assert 'println!("v2")' in result.rust
    kinds = [row["reply_kind"] for row in result.extra["baseline"]["rounds"]]
    assert kinds[1] == "other"
    assert oracle.n == 1


def test_dynamic_m_monitor_fail_uses_the_real_feedback(tmp_path):
    """Monitor FAIL blocks even when stress, Shuttle and miri all pass.

    Budget is 1 so the only assessment is the post-loop one. Ignoring
    ``monitor.blocking`` would accept this program.
    """
    provider = ScriptedProvider([
        {"text": _rust(f'println!("{TERMINAL}");', "MONITOR_FAIL")},
    ])
    oracle = _GuardOracle(provider, 1)
    task = tmp_path / "task"
    task.mkdir()
    (task / "contract.json").write_text("{}", encoding="utf-8")
    (task / "gold.cir.json").write_text("{}", encoding="utf-8")
    result = run_baseline_cell(
        arm="DYNAMIC_M", task="t", requirements="do the thing",
        task_dir=task, terminal=TERMINAL, provider=provider, oracle=oracle,
        workdir=tmp_path / "cell", replicate=0, run_params=_params(call_budget=1),
        tools=ToolRunner(runner=_CmdRunner(), toolchain=None))
    assert result.accepted is False
    monitor = result.extra["baseline"]["rounds"][0]["tools"]["monitor"]
    assert monitor["category"] == "monitor_fail"
    assert result.extra["baseline"]["accept_reason"] == "budget_exhausted"
    assert result.rounds_used == 1
    assert oracle.n == 1


def test_dynamic_m_monitor_fail_blocks_and_unsupported_does_not(tmp_path):
    blocked = _SeqFeedback([False, False], reason="dynamic_monitor_pass")
    failed, _, oracle_f = _run(
        tmp_path / "fail", "DYNAMIC_M",
        [_rust('println!("a");'), _rust('println!("b");')],
        feedback=blocked, budget=2, min_calls=2)
    assert failed.accepted is False
    assert failed.rounds_used == 2
    assert oracle_f.n == 1

    clear = _SeqFeedback([True], reason="dynamic_monitor_pass")
    ok, provider, oracle_ok = _run(
        tmp_path / "ok", "DYNAMIC_M",
        [_rust('println!("a");')],
        feedback=clear, min_calls=1)
    assert ok.accepted is True
    assert ok.extra["baseline"]["accept_reason"] == "dynamic_monitor_pass"
    assert ok.rounds_used == 1
    assert len(provider.calls) == 1
    assert oracle_ok.n == 1


def test_feedback_and_oracle_directories_do_not_overlap(tmp_path):
    feedback = _SeqFeedback([False, True])
    result, _, oracle = _run(
        tmp_path, "STATIC",
        [_rust('println!("a");'), _rust('println!("b");')],
        feedback=feedback, min_calls=2)
    cell = tmp_path / "cell"
    assert oracle.workdirs == [cell]
    assert all("feedback" in str(path.relative_to(cell)) for path in feedback.dirs)
    assert all(path != cell for path in feedback.dirs)
    assert (cell / "compile").is_dir()
    assert result.oracle is not None


def test_classify_no_issues_only_with_the_flag():
    assert classify_rust_reply("NO_ISSUES", allow_no_issues=True).kind == "no_issues"
    assert classify_rust_reply("NO_ISSUES", allow_no_issues=False).kind == "other"


# ── real cmd_run path (fake client + source-sensitive runner only) ──

FIRST = _rust('println!("NOPE");', "CLIPPY_HIT SKELNET_WRONG MONITOR_FAIL")
CLEAN = _rust(f'println!("{TERMINAL}");')


def _source_of(cwd: Path) -> str:
    for base in (cwd, *cwd.parents):
        path = base / "src" / "main.rs"
        if path.is_file():
            return path.read_text(encoding="utf-8")
        if base.name in ("tmp", "pytest-of-ubuntu"):
            break
    return ""


def _in_shuttle(cwd: Path) -> bool:
    return any(part == "shuttle" for part in cwd.parts[-6:])


class _CmdRunner:
    """Outermost subprocess stand-in. Output follows markers in the source."""

    def __init__(self):
        self.argvs: list[list[str]] = []
        self.envs: list[dict] = []

    def __call__(self, cmd, cwd, timeout, env):
        cmd = [str(part) for part in cmd]
        cwd = Path(cwd)
        self.argvs.append(cmd)
        self.envs.append(dict(env))
        src = _source_of(cwd)
        name = Path(cmd[0]).name
        if "clippy" in cmd:
            return self._clippy(src)
        if name == "concir-instrument":
            return self._instrument(cmd, src)
        if name == "concir-backend":
            return self._backend(src)
        if env.get("RUSTC_WRAPPER"):
            return self._lockbud(src)
        if "miri" in cmd:
            return ns(0, TERMINAL + "\n", "")
        if "build" in cmd:
            if "NOCOMPILE" in src:
                payload = {"reason": "compiler-message", "message": {
                    "level": "error", "message": "boom", "code": {"code": "E0425"},
                    "rendered": "error[E0425]: boom\n"}}
                return ns(101, json.dumps(payload), "error[E0425]: boom")
            self._make_binary(cwd)
            return ns(0, "", "")
        if _in_shuttle(cwd) or name == "shuttle_probe":
            return ns(0, "", "")
        if "SKELNET_WRONG" in src:
            return ns(0, "NOPE\n", "")
        if env.get("CIR_TRACE_OUT"):
            Path(env["CIR_TRACE_OUT"]).write_text("", encoding="utf-8")
        return ns(0, TERMINAL + "\n", "")

    def _clippy(self, src: str):
        if "CLIPPY_HIT" not in src:
            return ns(0, "", "")
        payload = {"reason": "compiler-message", "message": {
            "level": "warning", "message": "Mutex<bool>",
            "code": {"code": "clippy::mutex_atomic"},
            "rendered": "warning: Mutex<bool>\n"}}
        return ns(0, json.dumps(payload) + "\n", "")

    def _lockbud(self, src: str):
        if "CLIPPY_HIT" in src:
            return ns(0, "", '{"bug_kind": "DoubleLock"}\n')
        return ns(0, "", "Possible bugs: conflictlock 0\n")

    def _instrument(self, cmd, src: str):
        out = Path(cmd[cmd.index("--out") + 1])
        out.mkdir(parents=True, exist_ok=True)
        body = src
        if "MONITOR_UNSUP" in src:
            body = "fn main() { thread::spawn(|| {}); }\n" + src
        (out / "annotated.rs").write_text(body, encoding="utf-8")
        (out / "cir_trace.rs").write_text("// runtime\n", encoding="utf-8")
        (out / "resources.json").write_text(
            json.dumps({"resources": DEFAULT_RESOURCES}), encoding="utf-8")
        return ns(0, "", "")

    def _backend(self, src: str):
        if "MONITOR_FAIL" in src:
            report = {"properties": [{
                "id": "safety-main", "kind": "safety", "source": "properties",
                "req": "R1", "status": "FAIL", "detail": "both locks held",
            }]}
        else:
            report = DEFAULT_REPORT
        return ns(0, json.dumps(report), "")

    def _make_binary(self, cwd: Path):
        text = ""
        toml = cwd / "Cargo.toml"
        if toml.is_file():
            text = toml.read_text(encoding="utf-8")
        name = "probe"
        for line in text.splitlines():
            if line.strip().startswith("name"):
                name = line.split("=", 1)[1].strip().strip('"')
                break
        binary = cwd / "target" / "debug" / name
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text("", encoding="utf-8")


class _Client:
    def __init__(self, replies):
        self.replies = list(replies)
        self.n = 0
        self.users: list[str] = []

    def complete(self, system, user):
        self.n += 1
        self.users.append(user)
        text = self.replies[self.n - 1] if self.n <= len(self.replies) else CLEAN
        return SimpleNamespace(
            text=text, usage=None, requested_model="deepseek-v4-flash",
            response_model=None, request_id="r", transport_attempt=1,
            cost=None, finish_reason="stop")


def _cmd(tmp_path, arm, replies, *, name="run"):
    runner = _CmdRunner()
    holder = {}

    def factory(spec, out):
        holder["client"] = _Client(replies)
        return holder["client"]

    out = tmp_path / name
    args = cli.build_parser().parse_args([
        "run", "--arm", arm, "--tasks", "lock-order/abba_2lock",
        "--reps", "1", "--rounds", "1", "--call-budget", "5",
        "--out", str(out), "--allow-missing-tools",
        "--budget-file", str(tmp_path / f"budget-{name}.json"),
    ])
    rc = cli.cmd_run(args, client_factory=factory, oracle_runner=runner)
    cell_path = out / "cells" / "lock-order" / "abba_2lock" / "0" / "result.json"
    cell = json.loads(cell_path.read_text(encoding="utf-8"))
    return rc, cell, holder["client"], runner, out


def test_cmd_run_refine_real_path(tmp_path):
    rc, cell, client, runner, _out = _cmd(
        tmp_path, "REFINE", [FIRST, "NO_ISSUES"])
    assert rc == 0
    assert validate_cell(cell) == []
    assert cell["accepted"] is True
    assert cell["baseline"]["accept_reason"] == "no_issues"
    assert cell["calls"][0]["stage"] == "generate"
    assert cell["calls"][1]["stage"] == "review"
    assert client.n == 2
    assert any("build" in " ".join(argv) for argv in runner.argvs)


def test_cmd_run_static_real_path(tmp_path):
    rc, cell, client, runner, _out = _cmd(
        tmp_path, "STATIC", [FIRST, CLEAN])
    assert rc == 0
    assert cell["accepted"] is True
    assert cell["baseline"]["accept_reason"] == "static_clean"
    assert cell["rounds_used"] == 2
    assert any("clippy" in argv for argv in runner.argvs)
    assert any(env.get("RUSTC_WRAPPER") for env in runner.envs)
    joined = "\n".join(
        (row.get("feedback_sha256") or "") for row in cell["baseline"]["rounds"])
    assert "function_completed" not in json.dumps(cell["baseline"])
    assert joined  # feedback was recorded


def test_cmd_run_dynamic_real_path(tmp_path):
    rc, cell, client, runner, _out = _cmd(
        tmp_path, "DYNAMIC", [FIRST, CLEAN])
    assert rc == 0
    assert cell["accepted"] is True
    assert cell["baseline"]["accept_reason"] == "dynamic_pass"
    assert cell["rounds_used"] == 2
    seeds = [env.get("SHUTTLE_RANDOM_SEED") for env in runner.envs
             if env.get("SHUTTLE_RANDOM_SEED")]
    assert seeds, runner.envs
    from skelnet.rusttools.seeds import FEEDBACK_SHUTTLE_SEED, ORACLE_SHUTTLE_SEED
    assert str(FEEDBACK_SHUTTLE_SEED) in seeds
    assert str(ORACLE_SHUTTLE_SEED) in seeds


def test_cmd_run_dynamic_m_real_path(tmp_path):
    rc, cell, client, runner, out = _cmd(
        tmp_path, "DYNAMIC_M", [FIRST, CLEAN])
    assert rc == 0
    assert cell["accepted"] is True
    assert cell["baseline"]["accept_reason"] == "dynamic_monitor_pass"
    sent = "\n".join(client.users)
    for forbidden in ("function_completed", "holds_all(", "design_loss",
                      "extra_sync", "gold.cir", "requirements.json"):
        assert forbidden not in sent
    cell_dir = out / "cells" / "lock-order" / "abba_2lock" / "0"
    assert (cell_dir / "candidate.rs").is_file()
    assert (cell_dir / "feedback").is_dir()
    assert (cell_dir / "compile").is_dir()


def test_cmd_run_dynamic_m_instrument_unsupported_accepts(tmp_path):
    unsup = _rust(f'println!("{TERMINAL}");', "MONITOR_UNSUP")
    rc, cell, _client, _runner, _out = _cmd(
        tmp_path, "DYNAMIC_M", [unsup], name="unsup")
    assert rc == 0
    assert cell["accepted"] is True
    assert cell["baseline"]["accept_reason"] == "dynamic_monitor_pass"
    assert cell["rounds_used"] == 1
    assert cell["baseline"]["accepted_at_call"] == 1
