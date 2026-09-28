from pathlib import Path

from skelnet.env import load_dotenv
from skelnet.json_utils import extract_json
from skelnet.transport import ModelIdentityError, verify_identity
from skelnet.models import normalize_token_usage


def test_load_dotenv_does_not_override_by_default(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('FOO="bar"\n# comment\nBAZ=1\n', encoding="utf-8")
    monkeypatch.setenv("FOO", "keep")
    load_dotenv(env)
    import os
    assert os.environ["FOO"] == "keep"
    assert os.environ["BAZ"] == "1"
    load_dotenv(env, override=True)
    assert os.environ["FOO"] == "bar"


def test_extract_json_strips_fences_and_think():
    text = "```json\n{\"a\": 1}\n```"
    assert extract_json(text) == '{"a": 1}'
    assert extract_json("ok <think>x</think> {\"b\": 2} tail") == '{"b": 2}'


def test_normalize_token_usage():
    assert normalize_token_usage({"prompt_tokens": 3, "completion_tokens": 4}) == {
        "input": 3, "output": 4, "reasoning": None, "cached": None}
    assert normalize_token_usage(None) == {
        "input": None, "output": None, "reasoning": None, "cached": None}
    assert normalize_token_usage({
        "prompt_tokens": 3, "completion_tokens": 4,
        "completion_tokens_details": {"reasoning_tokens": 2},
        "prompt_tokens_details": {"cached_tokens": 1},
    }) == {"input": 3, "output": 4, "reasoning": 2, "cached": 1}


def test_verify_identity():
    assert verify_identity("m", "m") is True
    assert verify_identity("m", None) is False
    try:
        verify_identity("m", "other")
    except ModelIdentityError:
        pass
    else:
        raise AssertionError("expected ModelIdentityError")
