"""T10: OpenCode Chat (Kimi) keeps usage when both attempts are truncated."""

from _fake_sdk import FakeSDK, chat_response, sequence_handler

from test_truncation_accounting import USAGE, _cell, _run


def test_kimi_twice_truncated_keeps_usage(tmp_path, monkeypatch):
    sdk = FakeSDK(chat_handler=sequence_handler([
        chat_response("", finish_reason="length", usage=USAGE),
        chat_response("", finish_reason="length", usage=USAGE),
    ]))
    out, rc = _run(tmp_path, monkeypatch, "Kimi", sdk)
    assert rc == 0
    cell = _cell(out, "Kimi")
    assert cell["error"] == "transport_truncated"
    call = cell["calls"][0]
    assert len(call["finish_reasons"]) == 2
    assert call["usage"]["input"] == 20
    assert call["usage"]["output"] == 10
    # Billable = input + output over both attempts.
    assert cell["budget_used"]["tokens"] == 30
