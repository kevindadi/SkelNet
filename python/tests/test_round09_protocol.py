"""R9-P1/P2: the frozen protocol, its renderer, and drift detection."""

import hashlib
import json
import shutil
from pathlib import Path

from skelnet import cli, params, prompts, protocol
from skelnet.oracle import FakeOracle


def _fake_repo(root: Path) -> Path:
    task = root / "benchmarks" / "tasks" / "fam" / "one"
    task.mkdir(parents=True)
    (task / "contract.json").write_text("{}\n", encoding="utf-8")
    (task / "requirements.json").write_text(
        json.dumps({"tier": "L1", "tier_source": "legacy"}) + "\n",
        encoding="utf-8")
    (task / "REQUIREMENTS.h1.md").write_text("R1. Work.\n", encoding="utf-8")
    (task / "gold.skel").write_text("skeleton x;\n", encoding="utf-8")
    (task / "rust").mkdir()
    (task / "rust" / "fixed.rs").write_text("fn main() {}\n", encoding="utf-8")
    (root / "benchmarks" / "TIERS.md").write_text("| task |\n| --- |\n",
                                                  encoding="utf-8")
    return root


def _doc(root: Path) -> dict:
    return protocol.build_protocol(root=root, fixed_time="2026-01-01T00:00:00Z",
                                   commit="c0ffee")


def _write_protocol(root: Path, doc: dict) -> Path:
    path = root / "experiments" / "protocol.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path


def _fields(mismatches) -> str:
    return " ".join(item["field"] for item in mismatches)


def test_build_is_deterministic_with_fixed_time(tmp_path):
    root = _fake_repo(tmp_path / "repo")
    assert _doc(root) == _doc(root)


def test_check_ok(tmp_path):
    root = _fake_repo(tmp_path / "repo")
    assert protocol.check_protocol(_doc(root), root) == []


def test_prompt_drift_names_arms_field(tmp_path, monkeypatch):
    root = _fake_repo(tmp_path / "repo")
    doc = _doc(root)
    prompts_copy = tmp_path / "prompts"
    shutil.copytree(prompts.PROMPT_ASSET_DIR, prompts_copy)
    asset = prompts_copy / prompts.SKEL_GENERATION_ASSET
    asset.write_text(asset.read_text(encoding="utf-8") + " ",
                     encoding="utf-8")
    monkeypatch.setattr(prompts, "PROMPT_ASSET_DIR", prompts_copy)
    mismatches = protocol.check_protocol(doc, root)
    assert mismatches
    assert any(item["field"].startswith("arms.routes.SKEL")
               for item in mismatches), _fields(mismatches)


def test_task_file_drift_names_benchmark_field(tmp_path):
    root = _fake_repo(tmp_path / "repo")
    doc = _doc(root)
    reqs = root / "benchmarks" / "tasks" / "fam" / "one" / "requirements.json"
    reqs.write_text(reqs.read_text(encoding="utf-8") + " ", encoding="utf-8")
    mismatches = protocol.check_protocol(doc, root)
    assert mismatches
    assert any(item["field"].startswith("benchmark")
               for item in mismatches), _fields(mismatches)


def test_run_params_drift_names_field(tmp_path, monkeypatch):
    root = _fake_repo(tmp_path / "repo")
    doc = _doc(root)
    monkeypatch.setattr(params, "DEFAULT_CALL_BUDGET", 6)
    mismatches = protocol.check_protocol(doc, root)
    assert any(item["field"] == "run_params.call_budget" for item in mismatches)


def test_oracle_seed_drift_names_field(tmp_path, monkeypatch):
    root = _fake_repo(tmp_path / "repo")
    doc = _doc(root)
    monkeypatch.setattr(protocol.seeds_mod, "ORACLE_SHUTTLE_SEED", 0xABC)
    mismatches = protocol.check_protocol(doc, root)
    assert any(item["field"] == "oracle.oracle_shuttle_seed"
               for item in mismatches), _fields(mismatches)


def test_render_is_deterministic_and_lists_sha(tmp_path):
    root = _fake_repo(tmp_path / "repo")
    path = _write_protocol(root, _doc(root))
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    doc = json.loads(raw.decode("utf-8"))
    first = protocol.render_markdown(doc, digest)
    second = protocol.render_markdown(doc, digest)
    assert first == second
    assert digest in first
    assert "generated from" in first
    assert "/Users/" not in first and "/private/" not in first


def test_check_cli_exit_codes(tmp_path, capsys):
    root = _fake_repo(tmp_path / "repo")
    path = _write_protocol(root, _doc(root))
    assert cli.main(["protocol", "check", "--protocol", str(path),
                     "--root", str(root)]) == 0
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["run_params"]["call_budget"] = 99
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    assert cli.main(["protocol", "check", "--protocol", str(path),
                     "--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "run_params.call_budget" in out


def test_run_stage1_refuses_mismatch(tmp_path, monkeypatch, capsys):
    root = _fake_repo(tmp_path / "repo")
    doc = _doc(root)
    doc["run_params"]["call_budget"] = 99
    _write_protocol(root, doc)
    monkeypatch.setattr(cli, "repo_root", lambda: root)
    called = {"provider": False}

    def _no_provider(*args, **kwargs):
        called["provider"] = True
        raise AssertionError("provider must not be built")

    monkeypatch.setattr(cli, "_build_provider", _no_provider)
    out = tmp_path / "run"
    rc = cli.main(["run", "--arm", "G0", "--tasks", "fam/one", "--reps", "1",
                   "--stage", "1", "--hint", "h1", "--out", str(out)])
    assert rc == 1
    assert called["provider"] is False
    assert not out.exists()
    assert "protocol check failed" in capsys.readouterr().err


def test_run_stage0_warns_but_continues(tmp_path, monkeypatch, capsys):
    root = tmp_path / "repo"
    task = root / "benchmarks" / "tasks" / "fam" / "one"
    task.mkdir(parents=True)
    (task / "contract.json").write_text("{}\n", encoding="utf-8")
    (task / "requirements.json").write_text(
        json.dumps({"terminal": "DONE t=1"}) + "\n", encoding="utf-8")
    (task / "REQUIREMENTS.h1.md").write_text("R1. Work.\n", encoding="utf-8")
    monkeypatch.setattr(cli, "repo_root", lambda: root)
    monkeypatch.setattr(cli, "_protocol_preflight",
                        lambda args, r: ("deadbeef", "fail",
                                         [{"field": "run_params.call_budget",
                                           "frozen": 5, "current": 99}]))
    out = tmp_path / "run"

    class Client:
        def complete(self, system, user):
            from types import SimpleNamespace
            return SimpleNamespace(
                text="```rust\nfn main() { println!(\"DONE t=1\"); }\n```",
                usage=None, requested_model="m", response_model=None,
                request_id="r", transport_attempt=1, cost=None,
                finish_reason="stop")

    args = cli.build_parser().parse_args([
        "run", "--arm", "G0", "--tasks", "fam/one", "--reps", "1",
        "--out", str(out), "--budget-file", str(tmp_path / "budget.json")])
    rc = cli.cmd_run(args, client_factory=lambda spec, o: Client(),
                     oracle_factory=lambda t, term: FakeOracle(True))
    assert rc == 0
    assert "protocol check failed" in capsys.readouterr().err
    manifest = json.loads((out / "MANIFEST.json").read_text())
    assert manifest["protocol_check"] == "fail"
    assert manifest["protocol_sha256"] == "deadbeef"
