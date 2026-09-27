import json
from pathlib import Path

from skelnet.backend import Backend, repo_root


def test_repo_root_is_skelnet():
    assert (repo_root() / "Cargo.toml").exists()


def test_check_and_lower_abba_gold():
    root = repo_root()
    skel = root / "benchmarks/tasks/lock-order/abba_2lock/gold.skel"
    contract = root / "benchmarks/tasks/lock-order/abba_2lock/contract.json"
    backend = Backend()
    check = backend.check(skel)
    assert check.kind == "semantic" and check.ok, check
    verify = backend.verify(skel, contract)
    assert verify.outcome == "PASS", verify
    assert (verify.payload or {}).get("unmapped") == 0


def test_lower_writes_program_and_map(tmp_path):
    root = repo_root()
    skel = root / "benchmarks/tasks/lock-order/abba_2lock/gold.skel"
    out = tmp_path / "p.cir.json"
    map_path = tmp_path / "p.map.json"
    backend = Backend()
    result = backend.lower(skel, out, map_path=map_path)
    assert result.exit_code == 0, result.stderr
    program = json.loads(out.read_text())
    assert program["entry"] == "main::main"
    source_map = json.loads(map_path.read_text())
    assert source_map["resources"]["main::a"]["span"]["line"] > 0


def test_invalid_skeleton_reports_s_code():
    root = repo_root()
    backend = Backend()
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "bad.skel"
        p.write_text("skeleton t;\nfn main() { lock nope { } }\n", encoding="utf-8")
        check = backend.check(p)
        assert not check.ok
        codes = [x["code"] for x in (check.payload or {}).get("diagnostics", [])]
        assert "S101" in codes
