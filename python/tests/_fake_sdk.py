"""Fake SDK objects shared by the client tests (no openai import)."""

from __future__ import annotations

from types import SimpleNamespace


def chat_response(text: str, *, finish_reason: str = "stop", usage=None,
                  model: str | None = None, request_id: str = "r1", cost=None,
                  reasoning: str | None = None):
    message = SimpleNamespace(content=text, reasoning_content=reasoning)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=usage, model=model, id=request_id,
                           cost=cost)


def responses_response(text: str, *, status: str = "completed",
                       incomplete_reason: str | None = None, usage=None,
                       model: str | None = None, request_id: str = "r1", cost=None):
    details = None
    if incomplete_reason is not None:
        details = SimpleNamespace(reason=incomplete_reason)
    return SimpleNamespace(output_text=text, status=status,
                           incomplete_details=details, usage=usage, model=model,
                           id=request_id, cost=cost)


def _attribute_model(response, requested):
    if response is None or requested is None:
        return response
    if hasattr(response, "model") and getattr(response, "model") is None:
        response.model = requested
    return response


def _as_stream(response, kwargs):
    """Adapt a non-streaming chat response to the streaming chunk protocol.

    Qwen/Kimi use ``stream=True`` by default (round 9d). Tests that build these
    real clients through ``channels.build_client`` return an ordinary
    ``chat_response``; this wraps it so ``DirectChatClient._parse_stream`` sees
    the expected chunk sequence without every test hand-building chunks.
    """
    choice = (getattr(response, "choices", None) or [None])[0]
    message = getattr(choice, "message", None)
    content = getattr(message, "content", None)
    reasoning = getattr(message, "reasoning_content", None)
    finish = getattr(choice, "finish_reason", None)
    model = getattr(response, "model", None)
    request_id = getattr(response, "id", None)
    chunks = []
    if content is not None or reasoning is not None:
        delta = SimpleNamespace(content=content, reasoning_content=reasoning)
        chunks.append(SimpleNamespace(
            choices=[SimpleNamespace(delta=delta, finish_reason=None)],
            model=model, id=request_id, usage=None))
    empty = SimpleNamespace(content=None, reasoning_content=None)
    chunks.append(SimpleNamespace(
        choices=[SimpleNamespace(delta=empty, finish_reason=finish)],
        model=model, id=request_id, usage=None))
    if (kwargs.get("stream_options") or {}).get("include_usage"):
        chunks.append(SimpleNamespace(choices=[], model=model, id=request_id,
                                      usage=getattr(response, "usage", None)))
    return chunks


class _ChatCompletions:
    def __init__(self, handler):
        self.handler = handler
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        response = _attribute_model(self.handler(kwargs), kwargs.get("model"))
        if kwargs.get("stream") and not hasattr(response, "__iter__"):
            return _as_stream(response, kwargs)
        return response


class _Responses:
    def __init__(self, handler):
        self.handler = handler
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _attribute_model(self.handler(kwargs), kwargs.get("model"))


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


def sequence_chat_handler(responses):
    """A chat handler returning the given texts in order."""
    iterator = iter(responses)

    def handler(_kwargs):
        return chat_response(next(iterator))
    return handler


def sequence_responses_handler(responses):
    iterator = iter(responses)

    def handler(_kwargs):
        return responses_response(next(iterator))
    return handler


def sequence_handler(responses):
    """Return already-built response objects in order (no re-wrapping)."""
    iterator = iter(responses)
    return lambda _kwargs: next(iterator)


_ORIGINAL_BUILD_CLIENT = None


def patch_build_client(monkeypatch, sdk):
    """Keep the real channels.build_client, only injecting a fake SDK + sleep.

    Repeated calls in one test must still reach the *original* function, not a
    previously patched wrapper.
    """
    global _ORIGINAL_BUILD_CLIENT
    from skelnet import channels
    if _ORIGINAL_BUILD_CLIENT is None:
        _ORIGINAL_BUILD_CLIENT = channels.build_client
    original = _ORIGINAL_BUILD_CLIENT

    def patched(spec, params, **kwargs):
        kwargs["sdk_client"] = sdk
        kwargs["sleep"] = lambda _seconds: None
        return original(spec, params, **kwargs)

    monkeypatch.setattr(channels, "build_client", patched)
    return patched


def write_env(tmp_path, **values):
    path = tmp_path / ".env"
    path.write_text("\n".join(f"{k}={v}" for k, v in values.items()) + "\n",
                    encoding="utf-8")
    return path


def terminal_pass_runner(stdout: str = "DONE t1=1 t2=1\n"):
    def run(cmd, cwd, timeout, env):
        if "build" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
    return run
