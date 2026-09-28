"""A1: only the real client path loads .env; the key never reaches artifacts."""

from skelnet import channels, cli
from skelnet.oracle import FakeOracle

from _fake_sdk import RUST, ScriptedTransportClient, run_args

SECRET = "SECRET-KEY-VALUE-123"


def test_env_file_loaded_and_key_not_leaked(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text(f"MOONSHOT_API_KEY={SECRET}\n", encoding="utf-8")
    seen: dict = {}

    def fake_build_client(spec, params, **kwargs):
        seen["key"] = kwargs["api_key"]
        return ScriptedTransportClient([RUST])

    monkeypatch.setattr(channels, "build_client", fake_build_client)

    out = tmp_path / "run"
    args = run_args("G0", out, model="Kimi", env_file=str(env))
    rc = cli.cmd_run(args, oracle_factory=lambda t, term: FakeOracle(True))
    assert rc == 0
    assert seen["key"] == SECRET

    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err
    for path in out.rglob("*"):
        if path.is_file():
            assert SECRET not in path.read_text(errors="ignore"), path
