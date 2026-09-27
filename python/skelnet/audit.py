"""Audit log: one JSONL record per real model call.

Records are content-addressed by sha256 and never contain API keys. Raw
prompt/response text is optional and written under ``raw_dir`` when provided.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path: Path | str, raw_dir: Path | str | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.raw_dir = Path(raw_dir) if raw_dir else None
        if self.raw_dir:
            self.raw_dir.mkdir(parents=True, exist_ok=True)

    def _write(self, record: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def model_call(self, *, run_id: str, cell_id: str, model: str, provider: str,
                   transport: str, arm: str, task_id: str, replicate: int,
                   stage: str, requested_model: str, returned_model: str | None,
                   usage_raw: dict[str, Any] | None, started_at: float,
                   ended_at: float, prompt: str, response: str,
                   candidate_round: int | None = None,
                   status: str = "ok", attempt_id: str | None = None,
                   request_id: str | None = None, transport_attempt: int = 1,
                   cost: float | None = None, notes: str | None = None,
                   error_type: str | None = None, error: str | None = None,
                   **extra: Any) -> dict[str, Any]:
        prompt_sha = sha256_text(prompt)
        response_sha = sha256_text(response) if response else None
        if self.raw_dir:
            (self.raw_dir / f"{prompt_sha}.prompt.txt").write_text(prompt, encoding="utf-8")
            if response:
                (self.raw_dir / f"{response_sha}.response.txt").write_text(
                    response, encoding="utf-8")
        record = {
            "run_id": run_id, "cell_id": cell_id, "model": model,
            "provider": provider, "transport": transport, "arm": arm,
            "task_id": task_id, "replicate": replicate, "stage": stage,
            "requested_model": requested_model, "returned_model": returned_model,
            "usage_raw": usage_raw, "prompt_sha256": prompt_sha,
            "response_sha256": response_sha,
            "wall_ms": int(max(0.0, ended_at - started_at) * 1000),
            "candidate_round": candidate_round, "status": status,
            "attempt_id": attempt_id, "request_id": request_id,
            "transport_attempt": transport_attempt, "cost": cost, "notes": notes,
            "error_type": error_type, "error": error,
        }
        record.update(extra)
        self._write(record)
        return record


def read_events(path: Path | str) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
