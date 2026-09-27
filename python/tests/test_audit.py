from skelnet.audit import AuditLog, read_events, sha256_text


def test_model_call_record_hashes_and_no_secret(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl", raw_dir=tmp_path / "raw")
    record = log.model_call(
        run_id="r", cell_id="c", model="m", provider="p", transport="t",
        arm="SKEL", task_id="task", replicate=0, stage="skel",
        requested_model="m-1", returned_model="m-1", usage_raw={"prompt_tokens": 1},
        started_at=1.0, ended_at=2.0, prompt="hello", response="world")
    assert record["prompt_sha256"] == sha256_text("hello")
    assert record["response_sha256"] == sha256_text("world")
    assert "api_key" not in record
    events = read_events(tmp_path / "audit.jsonl")
    assert events and events[0]["wall_ms"] == 1000
    assert (tmp_path / "raw").exists()
