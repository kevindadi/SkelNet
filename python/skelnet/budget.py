"""Global request/token budget ledger and per-cell budgets.

The ledger is a JSON file keyed by stage; it accumulates across process
restarts and is written atomically after every call. Cache hits and transport /
truncation retries never touch it.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .models import billable_tokens
from .transport import BudgetExceeded


class BudgetLedger:
    def __init__(self, path: Path | str, *, stage: int | str = 0,
                 limits: dict[str, dict[str, int]] | None = None) -> None:
        self.path = Path(path)
        self.stage = str(stage)
        self.data = self._load()
        if limits is None:
            # Limits are configured in the ledger file itself.
            self.limits = dict(self.data.get("limits") or {})
        else:
            self.limits = limits
            self.data["limits"] = limits

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {"stages": {}}
        return {"stages": {}}

    def _stage_data(self) -> dict[str, int]:
        stages = self.data.setdefault("stages", {})
        return stages.setdefault(self.stage,
                                 {"requests": 0, "input": 0, "output": 0,
                                  "reasoning": 0})

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".budget-",
                                   suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, indent=2)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def check(self) -> None:
        """Raise BudgetExceeded when the stage is already at/over its limits."""
        data = self._stage_data()
        limits = self.limits.get(self.stage, {})
        max_requests = limits.get("max_requests")
        max_tokens = limits.get("max_tokens")
        tokens = billable_tokens({"input": data["input"], "output": data["output"],
                                  "reasoning": data["reasoning"]})
        if max_requests is not None and data["requests"] >= max_requests:
            raise BudgetExceeded(
                f"stage {self.stage}: request budget exhausted "
                f"({data['requests']}/{max_requests})")
        if max_tokens is not None and tokens >= max_tokens:
            raise BudgetExceeded(
                f"stage {self.stage}: token budget exhausted ({tokens}/{max_tokens})")

    def reserve(self) -> None:
        """Count one real request (called by the clients before sending)."""
        self.check()
        self._stage_data()["requests"] += 1
        self._save()

    def add_tokens(self, tokens: dict[str, int | None] | None) -> None:
        if not tokens:
            return
        data = self._stage_data()
        for key in ("input", "output", "reasoning"):
            value = tokens.get(key)
            if isinstance(value, int):
                data[key] += value
        self._save()

    def snapshot(self) -> dict[str, Any]:
        return dict(self._stage_data())


class CellBudget:
    """Per-cell call and token budget (truncation/transport retries excluded)."""

    def __init__(self, *, call_budget: int, token_budget: int) -> None:
        self.call_budget = call_budget
        self.token_budget = token_budget
        self.calls = 0
        self.tokens = 0

    def check(self) -> str | None:
        if self.calls >= self.call_budget:
            return "cell_budget_exhausted"
        if self.tokens >= self.token_budget:
            return "cell_budget_exhausted"
        return None

    def count_call(self) -> None:
        self.calls += 1

    def add_tokens(self, tokens: dict[str, int | None] | None) -> None:
        self.tokens += billable_tokens(tokens)

    def snapshot(self) -> dict[str, int]:
        return {"calls": self.calls, "tokens": self.tokens}
