"""Small environment loader for local CLI use.

The project deliberately does not require ``python-dotenv`` just to read the
two local API keys. Existing environment variables always take precedence.
"""

from __future__ import annotations

import os
from pathlib import Path

def load_dotenv(path: Path | str, *, override: bool = False) -> None:
    """Load simple ``KEY=VALUE`` entries from *path* into ``os.environ``.

    By default an already-exported environment variable wins (the historical
    behaviour). Experiment runners pass ``override=True`` so the project's
    ``.env`` is authoritative and a stale shell export cannot shadow a rotated
    key.
    """

    dotenv_path = Path(path)
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if override:
            os.environ[key] = value
        else:
            os.environ.setdefault(key, value)
