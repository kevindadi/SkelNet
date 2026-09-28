"""Fake SDK objects shared by the client tests (no openai import)."""

from __future__ import annotations

from types import SimpleNamespace


def chat_response(text: str, *, finish_reason: str = "stop", usage=None,
                  model: str = "m", request_id: str = "r1", cost=None,
                  reasoning: str | None = None):
    message = SimpleNamespace(content=text, reasoning_content=reasoning)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=usage, model=model, id=request_id,
                           cost=cost)


def responses_response(text: str, *, status: str = "completed",
                       incomplete_reason: str | None = None, usage=None,
                       model: str = "m", request_id: str = "r1", cost=None):
    details = None
    if incomplete_reason is not None:
        details = SimpleNamespace(reason=incomplete_reason)
    return SimpleNamespace(output_text=text, status=status,
                           incomplete_details=details, usage=usage, model=model,
                           id=request_id, cost=cost)


class _ChatCompletions:
    def __init__(self, handler):
        self.handler = handler
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.handler(kwargs)


class _Responses:
    def __init__(self, handler):
        self.handler = handler
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.handler(kwargs)


class FakeSDK:
    """Minimal OpenAI-shaped SDK with chat and responses surfaces."""

    def __init__(self, *, chat_handler=None, responses_handler=None):
        self.chat = SimpleNamespace(
            completions=_ChatCompletions(chat_handler or (lambda k: chat_response("OK"))))
        self.responses = _Responses(responses_handler or (lambda k: responses_response("OK")))


class APIConnectionError(Exception):
    pass


class TransportOutcome:
    def __init__(self, text: str, usage=None, finish_reason: str = "stop") -> None:
        self.text = text
        self.usage = usage
        self.requested_model = "m"
        self.response_model = None
        self.request_id = "r1"
        self.transport_attempt = 1
        self.cost = None
        self.finish_reason = finish_reason


class ScriptedTransportClient:
    """A `complete(system, user)` client replaying fixed texts."""

    def __init__(self, responses, usage=None) -> None:
        self.responses = list(responses)
        self.usage = usage
        self.system_prompts: list[str] = []
        self.calls: list[tuple[str, str]] = []
        self._cursor = 0

    def complete(self, system: str, user: str):
        self.system_prompts.append(system)
        self.calls.append((system, user))
        text = self.responses[self._cursor] if self._cursor < len(self.responses) else ""
        self._cursor += 1
        return TransportOutcome(text, usage=self.usage)


BUGGY = """```skel
skeleton abba_bug;
mutex a;
mutex b;
fn main() { scope { spawn t1(); spawn t2(); } }
fn t1() { lock a { lock b { } } }
fn t2() { lock b { lock a { } } }
```"""

BUGGY2 = BUGGY.replace("fn t2() { lock b { lock a { } } }",
                       "fn t2() { lock b { } }")

FIXED = BUGGY.replace("fn t2() { lock b { lock a { } } }",
                      "fn t2() { lock a { lock b { } } }")

RUST = "```rust\nfn main() { println!(\"DONE\"); }\n```"


def run_args(arm, out, *, tasks="lock-order/abba_2lock", reps=1, rounds=1,
             model="DeepSeek Flash", **extra):
    from skelnet import cli
    argv = ["run", "--arm", arm, "--model", model, "--tasks", tasks,
            "--reps", str(reps), "--rounds", str(rounds), "--out", str(out)]
    for key, value in extra.items():
        argv.append("--" + key.replace("_", "-"))
        if value is not True:
            argv.append(str(value))
    return cli.build_parser().parse_args(argv)


def terminal_pass_runner(stdout: str = "DONE t1=1 t2=1\n"):
    def run(cmd, cwd, timeout, env):
        if "build" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
    return run
