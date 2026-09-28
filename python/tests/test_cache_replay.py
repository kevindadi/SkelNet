"""B4: response cache and offline replay."""

import json

import pytest

from skelnet import cli
from skelnet.cache import CachedClient, ResponseCache
from skelnet.oracle import FakeOracle
from skelnet.params import RunParams
from skelnet.transport import ReplayMiss

from _fake_sdk import RUST, ScriptedTransportClient, TransportOutcome, run_args


class _Inner:
    def __init__(self, text):
        self.text = text
        self.calls = 0

    def complete(self, system, user):
        self.calls += 1
        return TransportOutcome(self.text)


def test_cache_hit_and_replay(tmp_path):
    cache = ResponseCache(tmp_path / "cache")
    params = RunParams()
    inner = _Inner("hello")
    first = CachedClient(inner, cache=cache, replay=None, model_id="m", params=params)
    assert first.complete("sys", "user").text == "hello"
    assert inner.calls == 1

    inner2 = _Inner("other")
    second = CachedClient(inner2, cache=cache, replay=None, model_id="m", params=params)
    assert second.complete("sys", "user").text == "hello"
    assert inner2.calls == 0 and second.cache_hit

    inner3 = _Inner("other")
    replay = CachedClient(inner3, cache=ResponseCache(tmp_path / "empty"),
                          replay=cache, model_id="m", params=params)
    assert replay.complete("sys", "user").text == "hello"
    assert inner3.calls == 0

    with pytest.raises(ReplayMiss):
        miss = CachedClient(_Inner("x"), cache=ResponseCache(tmp_path / "e2"),
                            replay=cache, model_id="m", params=params)
        miss.complete("different", "user")


class _NeverClient:
    def complete(self, *args, **kwargs):
        raise AssertionError("replayed call reached the network")


def test_replay_via_cmd_run(tmp_path):
    out1 = tmp_path / "run1"
    client = ScriptedTransportClient([RUST])
    cli.cmd_run(run_args("G0", out1), client_factory=lambda spec, o: client,
                oracle_factory=lambda t, term: FakeOracle(True))
    assert client.calls

    out2 = tmp_path / "run2"
    args = run_args("G0", out2, replay_from=str(out1 / "cache"))
    rc = cli.cmd_run(args, client_factory=lambda spec, o: _NeverClient(),
                     oracle_factory=lambda t, term: FakeOracle(True))
    assert rc == 0
    result = json.loads((out2 / "cells" / "lock-order" / "abba_2lock" / "0"
                         / "result.json").read_text())
    assert result["status"] == "ok"
    assert result["calls"][0]["cache_hit"] is True
