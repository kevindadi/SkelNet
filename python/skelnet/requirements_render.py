"""Render the requirements text sent to the model.

Only the task's ``REQUIREMENTS.md`` (hint h0) or ``REQUIREMENTS.h1.md`` (hint
h1) is used — never ``requirements.json`` (which carries the contract clauses,
``unverifiable`` list and the task path) and never the task path as a
fallback. A trailing ``[U]`` marker is stripped; everything else is preserved.
"""

from __future__ import annotations

import re
from pathlib import Path

_HINT_FILES = {"h0": "REQUIREMENTS.md", "h1": "REQUIREMENTS.h1.md"}
_UNVERIFIABLE_MARKER = re.compile(r"\s*\[U\]\s*$")


class RequirementsMissing(Exception):
    """No requirements text exists for the requested hint."""


def render_requirements(task_dir: Path | str, hint: str = "h0") -> str:
    filename = _HINT_FILES.get(hint)
    if filename is None:
        raise RequirementsMissing(f"unsupported hint {hint!r}")
    path = Path(task_dir) / filename
    if not path.exists():
        raise RequirementsMissing(f"no requirements text at {path}")
    lines = [_UNVERIFIABLE_MARKER.sub("", line)
             for line in path.read_text(encoding="utf-8").splitlines()]
    text = "\n".join(lines).strip()
    if not text:
        raise RequirementsMissing(f"empty requirements text at {path}")
    return text + "\n"
