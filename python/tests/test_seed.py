"""B1: per-cell seeds are deterministic, arm-independent, and policy-gated."""

from skelnet.opencode_go import OpenCodeGoClient
from skelnet.params import RunParams, seed_for

from _fake_sdk import FakeSDK, chat_response


class _Budget:
    def reserve(self):
        return None


def test_seed_is_stable_and_arm_independent():
    assert seed_for("lock-order/abba_2lock", 0) == seed_for("lock-order/abba_2lock", 0)
    assert seed_for("lock-order/abba_2lock", 0) != seed_for("lock-order/abba_2lock", 1)
    assert seed_for("lock-order/abba_2lock", 0) != seed_for("lock-order/cycle_3lock", 0)


def test_seed_policy_none_omits_seed(tmp_path):
    sdk = FakeSDK(chat_handler=lambda k: chat_response("OK"))
    params = RunParams(seed_policy="none", supports_seed=True)
    client = OpenCodeGoClient(api_key="x", base_url="http://x", model="m",
                              budget=_Budget(), evidence_dir=tmp_path,
                              params=params, sdk_client=sdk)
    client.set_cell("task", 0)
    client.complete("s", "u")
    assert "seed" not in sdk.chat.completions.calls[0]


def test_seed_policy_per_cell_sends_seed(tmp_path):
    sdk = FakeSDK(chat_handler=lambda k: chat_response("OK"))
    params = RunParams(seed_policy="per_cell", supports_seed=True)
    client = OpenCodeGoClient(api_key="x", base_url="http://x", model="m",
                              budget=_Budget(), evidence_dir=tmp_path,
                              params=params, sdk_client=sdk)
    client.set_cell("task", 2)
    client.complete("s", "u")
    assert sdk.chat.completions.calls[0]["seed"] == seed_for("task", 2)
