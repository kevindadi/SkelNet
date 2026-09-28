"""T11: the first baseline call shares G0's cache entry.

Every test goes through ``cmd_run``. The inner client is counted; a cache hit
must not call it. ``--first-round require-cache`` misses without calling the
inner client or the oracle runner.
"""

import json
from types import SimpleNamespace

from skelnet import cli

from test_round04_baselines import CLEAN, FIRST, _CmdRunner

_TASK = "lock-order/abba_2lock"


class _Inner:
    def __init__(self):
        self.n = 0
        self.users: list[str] = []

    def complete(self, system, user):
        self.n += 1
        self.users.append(user)
        if "exactly NO_ISSUES" in user:
            text = "NO_ISSUES"
        elif "<tool_feedback" in user or "<rustc_diagnostics>" in user:
            text = CLEAN
        else:
            text = FIRST
        return SimpleNamespace(
            text=text, usage=None, requested_model="deepseek-v4-flash",
            response_model=None, request_id="r", transport_attempt=1,
            cost=None, finish_reason="stop")


def _run(tmp_path, arm, *, cache, name, reps=1, first_round="auto",
         replay=None, runner=None):
    holder = {}

    def factory(spec, out):
        holder["inner"] = _Inner()
        return holder["inner"]

    out = tmp_path / name
    argv = [
        "run", "--arm", arm, "--tasks", _TASK, "--reps", str(reps),
        "--rounds", "1", "--call-budget", "5", "--out", str(out),
        "--cache-dir", str(cache), "--allow-missing-tools",
        "--first-round", first_round,
        "--budget-file", str(tmp_path / f"budget-{name}.json"),
    ]
    if replay is not None:
        argv += ["--replay-from", str(replay)]
    args = cli.build_parser().parse_args(argv)
    rc = cli.cmd_run(args, client_factory=factory, oracle_runner=runner or _CmdRunner())
    cells = []
    for path in sorted((out / "cells").rglob("result.json")):
        cells.append(json.loads(path.read_text(encoding="utf-8")))
    return rc, cells, holder["inner"]


def _cell(cells, rep=0):
    return next(cell for cell in cells if cell["rep"] == rep)


def test_g0_then_baselines_share_the_first_call(tmp_path):
    cache = tmp_path / "cache"
    rc, g0_cells, g0_inner = _run(tmp_path, "G0", cache=cache, name="g0")
    assert rc == 0
    assert g0_inner.n == 1
    g0_sha = _cell(g0_cells)["calls"][0]["request_sha256"]
    assert _cell(g0_cells)["calls"][0]["cache_hit"] is False

    for arm in ("REFINE", "STATIC", "DYNAMIC", "DYNAMIC_M"):
        rc, cells, inner = _run(tmp_path, arm, cache=cache, name=arm.lower())
        assert rc == 0, arm
        cell = _cell(cells)
        assert cell["calls"][0]["cache_hit"] is True, arm
        assert cell["calls"][0]["request_sha256"] == g0_sha, arm
        assert cell["baseline"]["first_round_cache_hit"] is True, arm
        # Call 1 was served from the cache. Later calls are real.
        assert inner.n == cell["rounds_used"] - 1, (arm, inner.n, cell["rounds_used"])
        assert cell["rounds_used"] >= 2 or arm == "G0"
        if cell["rounds_used"] >= 2:
            assert cell["calls"][1]["cache_hit"] is False


def test_baseline_first_then_g0_hits(tmp_path):
    cache = tmp_path / "cache"
    rc, refine_cells, refine_inner = _run(
        tmp_path, "REFINE", cache=cache, name="refine")
    assert rc == 0
    assert refine_inner.n >= 1
    sha = _cell(refine_cells)["calls"][0]["request_sha256"]

    rc, g0_cells, g0_inner = _run(tmp_path, "G0", cache=cache, name="g0")
    assert rc == 0
    assert g0_inner.n == 0
    assert _cell(g0_cells)["calls"][0]["cache_hit"] is True
    assert _cell(g0_cells)["calls"][0]["request_sha256"] == sha


def test_require_cache_miss_does_not_call_inner_or_oracle(tmp_path):
    runner = _CmdRunner()
    rc, cells, inner = _run(
        tmp_path, "REFINE", cache=tmp_path / "empty", name="miss",
        first_round="require-cache", runner=runner)
    assert rc == 0
    cell = _cell(cells)
    assert cell["error"] == "first_round_miss"
    assert inner.n == 0
    assert runner.argvs == []
    assert cell["oracle"]["ran"] is False
    assert cell.get("baseline", {}).get("final_version") in (0, None) or (
        cell["baseline"]["final_version"] == 0)


def test_different_reps_do_not_share(tmp_path):
    rc, cells, inner = _run(
        tmp_path, "G0", cache=tmp_path / "cache", name="reps", reps=2)
    assert rc == 0
    assert inner.n == 2
    assert all(cell["calls"][0]["cache_hit"] is False for cell in cells)
    # The request text is identical; the cache key still includes rep and seed.
    assert len(list((tmp_path / "cache").glob("*.json"))) == 2
