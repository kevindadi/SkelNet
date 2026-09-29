"""T2: report over real ``cmd_run`` outputs (fake client + fake runner only)."""

import json
from pathlib import Path
from types import SimpleNamespace

from skelnet import cli
from skelnet.rusttools.runner import ToolRunner

from _fake_sdk import run_args
from round03_helpers import FakeTools, ns
from test_pipeline_skel import FIXED
from test_round04_baselines import TERMINAL, _CmdRunner, _rust
from test_round05_budget import _CompileFailThenOk

RUST_GOOD = '```rust\nfn main() { println!("DONE"); }\n```'


class _CostClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.n = 0

    def complete(self, system, user):
        text = self.replies[self.n] if self.n < len(self.replies) else ""
        self.n += 1
        return SimpleNamespace(
            text=text,
            usage={"input_tokens": 1000, "output_tokens": 500,
                   "output_tokens_details": {"reasoning_tokens": 0},
                   "input_tokens_details": {"cached_tokens": 0}},
            finish_reason="stop", finish_reasons=["stop"], wall_ms=1200,
            transport_attempt=1, truncation_retry=False,
            requested_model="deepseek-flash", response_model=None,
            request_id="r", cost=None, cache_hit=False)


def _run_cmd(tmp_path, arm, replies, *, cache_dir=None, runner=None,
             rounds=1, budget=5, name=None):
    out = tmp_path / (name or arm.lower())
    extra = {"budget_file": str(tmp_path / f"budget-{out.name}.json")}
    if cache_dir is not None:
        extra["cache_dir"] = str(cache_dir)
    args = run_args(arm, out, rounds=rounds, call_budget=budget, **extra)
    client = _CostClient(replies)
    rc = cli.cmd_run(args, client_factory=lambda spec, o: client,
                     oracle_runner=runner or _CmdRunner())
    assert rc == 0
    return out, client


def test_report_over_real_cmd_run(tmp_path, monkeypatch):
    # F7: independent of whether lockbud/clippy are installed.
    lockbud = tmp_path / "lockbud"
    lockbud.write_text("", encoding="utf-8")
    monkeypatch.setenv("LOCKBUD_BIN", str(lockbud))
    monkeypatch.setattr(cli, "_clippy_version", lambda: "clippy 0.0 (test)")
    monkeypatch.setattr(cli, "_clippy_probe", lambda: {})
    cache = tmp_path / "cache"
    clean = _rust(f'println!("{TERMINAL}");')
    g0_run, _ = _run_cmd(tmp_path, "G0", [clean], cache_dir=cache,
                         name="g0")
    static_run, _ = _run_cmd(tmp_path, "STATIC", [clean], cache_dir=cache,
                             name="static")

    out = tmp_path / "skel"
    args = run_args("SKEL", out, rounds=1, call_budget=5,
                    budget_file=str(tmp_path / "budget-skel.json"))
    skel_client = _CostClient([FIXED, RUST_GOOD])
    tools = _CompileFailThenOk(FakeTools())
    assert cli.cmd_run(args, client_factory=lambda s, o: skel_client,
                       oracle_runner=tools) == 0

    # STATIC's first call is a shared-cache hit, but its usage still counts.
    static_cell = json.loads(
        (static_run / "cells" / "lock-order" / "abba_2lock" / "0"
         / "result.json").read_text(encoding="utf-8"))
    assert static_cell["baseline"]["first_round_cache_hit"] is True
    assert static_cell["calls"][0]["cache_hit"] is True
    assert static_cell["calls"][0]["usage"]["input"] == 1000

    report_dir = tmp_path / "report"
    rc = cli.main(["report", str(g0_run), str(static_run), str(out),
                   "--table", "all", "--figure", "anytime", "--format", "both",
                   "--out", str(report_dir), "--look", "2",
                   "--bootstrap", "200"])
    assert rc == 0

    main_tex = (report_dir / "tables" / "main.tex").read_text(encoding="utf-8")
    rows = {line.split("&")[0].strip(): line for line in main_tex.splitlines()
            if line.startswith("\\arm")}
    assert rows["\\arm{SKEL}"].split("&")[5].strip() != "--"  # pooled
    assert rows["\\arm{G0}"].split("&")[5].strip() != "--"
    assert rows["\\arm{STATIC}"].split("&")[5].strip() != "--"
    assert rows["\\arm{CIR}"].split("&")[5].strip() == "--"
    assert rows["\\arm{REFINE}"].split("&")[5].strip() == "--"

    document = json.loads((report_dir / "report.json").read_text(encoding="utf-8"))
    # Cell counts match tasks x reps for each run.
    cost = {row["label"]: row for row in document["tables"]["cost"]["rows"]}
    assert cost["G0"]["n"] == 1
    assert cost["STATIC"]["n"] == 1
    assert cost["SKEL"]["n"] == 1
    # D8-12: STATIC's cache-hit first call still carries G0's usage.
    assert cost["STATIC"]["input"] == cost["G0"]["input"] == 1000
    # R9a records baseline.rounds[].compile_wall_ms, so STATIC has tool time.
    assert cost["STATIC"]["tool_n"] == 1
    assert cost["STATIC"]["tool_ms"] is not None

    lockbud = document["tables"]["lockbud"]
    joined = lockbud["joined"]
    assert (joined["tp"] + joined["fp"] + joined["fn"] + joined["tn"]
            + joined["unavailable"] + joined["excluded"]) == 1
    assert joined["tn"] == 1  # clean STATIC v1, non-deadlocking G0
