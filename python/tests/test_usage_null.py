"""A8: token usage keeps missing fields as null and separates reasoning/cached."""

from skelnet.models import normalize_token_usage


def test_chat_details():
    usage = {
        "prompt_tokens": 10, "completion_tokens": 20,
        "completion_tokens_details": {"reasoning_tokens": 7},
        "prompt_tokens_details": {"cached_tokens": 3},
    }
    assert normalize_token_usage(usage) == {"input": 10, "output": 20,
                                            "reasoning": 7, "cached": 3}


def test_responses_details():
    usage = {
        "input_tokens": 5, "output_tokens": 6,
        "output_tokens_details": {"reasoning_tokens": 4},
        "input_tokens_details": {"cached_tokens": 1},
    }
    assert normalize_token_usage(usage) == {"input": 5, "output": 6,
                                            "reasoning": 4, "cached": 1}


def test_dashscope_final_chunk_usage():
    usage = {"prompt_tokens": 2, "completion_tokens": 3,
             "output_tokens_details": {"reasoning_tokens": 1}}
    assert normalize_token_usage(usage)["reasoning"] == 1


def test_missing_and_malformed_are_none():
    empty = {"input": None, "output": None, "reasoning": None, "cached": None}
    assert normalize_token_usage(None) == empty
    assert normalize_token_usage({}) == empty
    assert normalize_token_usage({"prompt_tokens": "nope",
                                  "completion_tokens": None}) == empty
