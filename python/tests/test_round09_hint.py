"""R9-P5: the default hint is h1; the hint never changes a system prompt."""

import json
from types import SimpleNamespace

from skelnet import cli
from skelnet.backend import repo_root, sha256_file
from skelnet.oracle import FakeOracle

RUST = "```rust\nfn main() { println!(\"DONE t1=1 t2=1\"); }\n```"
ARMS = ["G0", "SKEL", "CIR", "REFINE", "STATIC", "DYNAMIC", "DYNAMIC_M"]


class _Client:
    def complete(self, system, user):
        return SimpleNamespace(
            text=RUST, usage=None, requested_model="deepseek-flash",
            response_model=None, request_id="r", transport_attempt=1,
            cost=None, finish_reason="stop")


def _dry_run(extra=()):
    import contextlib
    import io
    buffer = io.StringIO()
    args = ["run", "--arm", "G0", "--tasks", "lock-order/abba_2lock",
            "--reps", "1", "--dry-run", *extra]
    with contextlib.redirect_stdout(buffer):
        rc = cli.main(args)
    assert rc == 0
    return json.loads(buffer.getvalue())


def test_dry_run_default_hint_is_h1():
    payload = _dry_run()
    assert payload["hint_source"] == "default"
    assert payload["run_params"]["hint"] == "h1"


def test_manifest_default_hint_is_h1(tmp_path):
    out = tmp_path / "run"
    args = cli.build_parser().parse_args([
        "run", "--arm", "G0", "--tasks", "lock-order/abba_2lock", "--reps", "1",
        "--out", str(out)])
    rc = cli.cmd_run(args, client_factory=lambda spec, o: _Client(),
                     oracle_factory=lambda t, term: FakeOracle(True))
    assert rc == 0
    manifest = json.loads((out / "MANIFEST.json").read_text())
    assert manifest["hint"] == "h1"
    assert manifest["hint_source"] == "default"
    assert manifest["run_params"]["hint"] == "h1"
    assert manifest["protocol_check"] == "pass"
    expected = sha256_file(repo_root() / "experiments" / "protocol.json")
    assert manifest["protocol_sha256"] == expected


def test_hint_only_changes_user_messages():
    for arm in ARMS:
        import contextlib
        import io
        default = io.StringIO()
        explicit = io.StringIO()
        base = ["run", "--arm", arm, "--tasks", "lock-order/abba_2lock",
                "--reps", "1", "--dry-run"]
        with contextlib.redirect_stdout(default):
            assert cli.main(base) == 0
        with contextlib.redirect_stdout(explicit):
            assert cli.main([*base, "--hint", "h0"]) == 0
        left = json.loads(default.getvalue())["prompt_routes"]
        right = json.loads(explicit.getvalue())["prompt_routes"]
        assert left == right, arm
