"""Contract-monitor feedback for DYNAMIC_M (D4-5).

The oracle's O4 layer also judges the program against the reference design
(``design_loss``, thread counts, ``extra_sync``). Those judgments are dropped
here. The model sees property id / kind / source / req / status / sanitized
detail, plus unmapped program resource names. It does not see the contract
goal, the contract file, or ``gold.cir.json``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from ..oracle import CONCIR_SYNC_CRATE, _tool_path
from .dynamic_feedback import pack_sections
from .monitor import evaluate_o4
from .runner import ToolRunner

_SAFETY_KINDS = {"safety", "never_holds_all", "unreachable"}
_REACH_KINDS = {"preserved", "reachable", "reachability", "always_reachable"}
_INSTRUMENT_NOTE = "monitor 无法插桩这种写法"


def _present(pid: str, policy: str, index: dict[str, str]) -> str:
    """Use round 5's ``present_property_id`` once that module defines it."""
    from .. import prompts
    fn = getattr(prompts, "present_property_id", None)
    if fn is None:
        return str(pid)
    return str(fn(str(pid), policy, index))


def _property_blocking(prop: dict) -> bool:
    kind = prop.get("kind")
    status = prop.get("status")
    if kind in _SAFETY_KINDS and status == "FAIL":
        return True
    if kind in _REACH_KINDS and status == "not_observed":
        return True
    if status == "unmapped":
        return True
    return False


def _crash_or_timeout(layer) -> bool:
    """Instrumented-run timeout/crash: a monitor_fail with no property report."""
    if layer.category != "monitor_fail":
        return False
    report = (layer.data or {}).get("report") or {}
    properties = report.get("properties") or []
    if properties:
        return False
    return True


@dataclass
class MonitorFeedback:
    status: str
    category: str | None
    blocking: bool
    feedback: str
    truncated: bool = False
    properties: list[dict] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)
    wall_ms: int = 0

    @property
    def feedback_sha256(self) -> str:
        return hashlib.sha256(self.feedback.encode("utf-8")).hexdigest()

    @property
    def feedback_bytes(self) -> int:
        return len(self.feedback.encode("utf-8"))

    def to_dict(self) -> dict:
        return {"status": self.status, "category": self.category,
                "blocking": self.blocking, "wall_ms": self.wall_ms,
                "unmapped": list(self.unmapped)}


def render_monitor_feedback(layer, *, property_ids: str = "keep",
                            id_index: dict[str, str] | None = None
                            ) -> MonitorFeedback:
    """Build disclosure-safe feedback from an ``evaluate_o4`` result."""
    from ..prompts import sanitize_detail
    index = id_index if id_index is not None else {}
    data = layer.data or {}
    report = data.get("report") or {}
    properties = report.get("properties") or []
    unmapped = [str(name) for name in (data.get("unmapped_program_resources") or [])]
    rendered: list[dict] = []
    blocking = False
    lines: list[str] = []
    if layer.category == "instrument_unsupported":
        lines.append(f"## monitor\n{_INSTRUMENT_NOTE}")
    if _crash_or_timeout(layer):
        blocking = True
        detail = layer.detail or "instrumented run failed"
        lines.append(f"## monitor run\n{detail}")
    for prop in properties:
        if _property_blocking(prop):
            blocking = True
        pid = _present(str(prop.get("id") or ""), property_ids, index)
        detail = sanitize_detail(prop.get("id"), prop.get("detail"))
        item = {
            "id": pid,
            "kind": prop.get("kind"),
            "source": prop.get("source"),
            "req": prop.get("req"),
            "status": prop.get("status"),
            "detail": detail,
        }
        rendered.append(item)
        lines.append(
            "## property\n"
            f"id: {item['id']}\n"
            f"kind: {item['kind']}\n"
            f"source: {item['source']}\n"
            f"req: {item['req']}\n"
            f"status: {item['status']}\n"
            f"detail: {item['detail']}"
        )
    if unmapped:
        lines.append("## unmapped program resources\n" + "\n".join(unmapped))
    if layer.category == "tool_missing" or layer.status == "unavailable":
        lines.append(f"## monitor\nmonitor unavailable: {layer.detail}")
    if not lines:
        lines.append("## monitor\nno blocking monitor result")
    feedback, truncated = pack_sections(lines)
    return MonitorFeedback(status=layer.status, category=layer.category,
                           blocking=blocking, feedback=feedback,
                           truncated=truncated, properties=rendered,
                           unmapped=unmapped, wall_ms=layer.wall_ms or 0)


def run_monitor_feedback(tools: ToolRunner, workdir: Path | str, source: str, *,
                         task_dir: Path | str, property_ids: str = "keep",
                         runs: int = 5, timeout: float = 300.0,
                         id_index: dict[str, str] | None = None
                         ) -> MonitorFeedback:
    """Run O4 in ``workdir`` (not the oracle cell directory) and render D4-5."""
    layer = evaluate_o4(
        tools, workdir, source, task_dir=task_dir,
        instrument_bin=_tool_path("concir-instrument", "CONCIR_INSTRUMENT"),
        backend_bin=_tool_path("concir-backend", "CONCIR_BACKEND"),
        concir_sync_path=CONCIR_SYNC_CRATE, runs=runs, timeout=timeout)
    return render_monitor_feedback(layer, property_ids=property_ids,
                                   id_index=id_index)
