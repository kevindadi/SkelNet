"""R9-P3: the global ledger is safe under concurrent writers (D9-7)."""

import multiprocessing
import time

from skelnet.budget import BudgetLedger


def _worker(path, n, limits, queue):
    from skelnet.budget import BudgetLedger as Ledger
    from skelnet.transport import BudgetExceeded
    ledger = Ledger(path, stage="0", limits=limits)
    ok = 0
    failed = 0
    for _ in range(n):
        try:
            ledger.reserve()
        except BudgetExceeded:
            failed += 1
            break
        ok += 1
        ledger.add_tokens({"input": 10, "output": 5, "reasoning": 2})
    queue.put((ok, failed))


def _run_workers(path, n, limits, *, procs=4, hook_sleep=0.001):
    import skelnet.budget as budget

    original = budget._CRITICAL_HOOK
    budget._CRITICAL_HOOK = (lambda: time.sleep(hook_sleep)) if hook_sleep else None
    ctx = multiprocessing.get_context("fork")
    queue = ctx.Queue()
    workers = [ctx.Process(target=_worker, args=(str(path), n, limits, queue))
               for _ in range(procs)]
    try:
        for worker in workers:
            worker.start()
        results = [queue.get(timeout=60) for _ in workers]
        for worker in workers:
            worker.join(timeout=60)
    finally:
        budget._CRITICAL_HOOK = original
    return results


def test_concurrent_reserve_and_tokens(tmp_path):
    path = tmp_path / "budget.json"
    results = _run_workers(path, 50, None)
    assert [ok for ok, _ in results] == [50, 50, 50, 50]
    snapshot = BudgetLedger(path, stage="0").snapshot()
    assert snapshot == {"requests": 200, "input": 2000, "output": 1000,
                        "reasoning": 400}


def test_concurrent_limit_is_not_exceeded(tmp_path):
    path = tmp_path / "budget.json"
    limits = {"0": {"max_requests": 120}}
    results = _run_workers(path, 50, limits)
    successes = sum(ok for ok, _ in results)
    assert successes == 120
    snapshot = BudgetLedger(path, stage="0", limits=limits).snapshot()
    assert snapshot["requests"] == 120
    # 120 reserves each add one token triple.
    assert snapshot["input"] == 1200
    assert snapshot["output"] == 600
    assert snapshot["reasoning"] == 240


def test_public_shape_and_single_process(tmp_path):
    path = tmp_path / "budget.json"
    ledger = BudgetLedger(path, stage="1")
    ledger.reserve()
    ledger.add_tokens({"input": 3, "output": 4})
    assert ledger.snapshot() == {"requests": 1, "input": 3, "output": 4,
                                 "reasoning": 0}
