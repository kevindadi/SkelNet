"""Capture the request kwargs of the three models unchanged by round 9c.

Run against a checkout of ``origin/main`` (via a git worktree) to write
``golden_kwargs.json``. ``test_round09c_kimi.py`` replays the same capture on
the round-9c branch and asserts the three models' payloads are unchanged.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))  # tests/ for _fake_sdk


class _Budget:
    def reserve(self) -> None:
        return None

    def add_tokens(self, _tokens) -> None:
        return None


def capture(model: str) -> dict:
    from skelnet import channels
    from skelnet.params import params_for_model
    from skelnet.transport import build_registry, resolve_model

    from _fake_sdk import FakeSDK, RUST, chat_response, responses_response

    spec = resolve_model(build_registry(), model)
    sdk = FakeSDK(chat_handler=lambda k: chat_response(RUST),
                  responses_handler=lambda k: responses_response(RUST))
    client = channels.build_client(spec, params_for_model(spec), budget=_Budget(),
                                   evidence_dir=Path(tempfile.mkdtemp()),
                                   api_key="x", sdk_client=sdk)
    client.set_cell("lock-order/abba_2lock", 0)
    client.complete("SYS", "USER")
    call = (sdk.responses.calls or sdk.chat.completions.calls)[0]
    # Drop prompt content and the per-session header (a fresh UUID each run);
    # what remains is the frozen model/parameter policy.
    for key in ("messages", "input", "instructions", "extra_headers"):
        call.pop(key, None)
    return call


def main() -> int:
    out = {model: capture(model)
           for model in ("DeepSeek Flash", "Qwen", "GPT 6 Luna")}
    (HERE / "golden_kwargs.json").write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("wrote", HERE / "golden_kwargs.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
