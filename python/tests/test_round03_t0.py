"""T0: generated projects are standalone workspaces (build inside a foreign one)."""

from pathlib import Path

from skelnet.oracle import RustOracle, cargo_toml

from round03_helpers import rust_tools


def test_cargo_toml_declares_workspace():
    assert "[workspace]" in cargo_toml("probe")


@rust_tools
def test_build_inside_foreign_workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "Cargo.toml").write_text("[workspace]\nmembers = []\n", encoding="utf-8")
    cell = ws / "cells" / "x"
    oracle = RustOracle(terminal=None, layers=("O1",))
    result = oracle.evaluate("fn main() {}\n", cell)
    assert result.layers["O1"].status == "pass", result.layers["O1"].detail
