"""P0: guard the three untested branches of cli._prepare_out's protection.

These tests never modify cli.py. Each target is under tmp_path, and every
protected path (repo root, cwd, HOME) is redirected into tmp_path so that only
the branch under test can block the clear.
"""

import pytest

from skelnet import cli


def _run_dir(path) -> None:
    """Make `path` look like a previous run directory."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "MANIFEST.json").write_text("{}", encoding="utf-8")
    (path / "sentinel.txt").write_text("keep", encoding="utf-8")


def _assert_untouched(path) -> None:
    assert (path / "sentinel.txt").exists()
    assert (path / "MANIFEST.json").exists()


def test_force_refuses_ancestor_of_protected_path(tmp_path, monkeypatch):
    # out is an ancestor of the current directory (but not equal to it), so
    # only the ancestor rule can stop the clear.
    out = tmp_path / "outer"
    _run_dir(out)
    work = out / "work"
    work.mkdir()
    monkeypatch.chdir(work)

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    fakerepo = tmp_path / "fakerepo"
    fakerepo.mkdir()
    monkeypatch.setattr(cli, "repo_root", lambda: fakerepo)

    with pytest.raises(SystemExit):
        cli._prepare_out(out, force=True)
    _assert_untouched(out)


def test_force_refuses_home_directory(tmp_path, monkeypatch):
    home = tmp_path / "home"
    _run_dir(home)
    monkeypatch.setenv("HOME", str(home))

    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)

    fakerepo = tmp_path / "fakerepo"
    fakerepo.mkdir()
    monkeypatch.setattr(cli, "repo_root", lambda: fakerepo)

    with pytest.raises(SystemExit):
        cli._prepare_out(home, force=True)
    _assert_untouched(home)


def test_force_refuses_symlink(tmp_path, monkeypatch):
    real = tmp_path / "real"
    _run_dir(real)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    fakerepo = tmp_path / "fakerepo"
    fakerepo.mkdir()
    monkeypatch.setattr(cli, "repo_root", lambda: fakerepo)

    with pytest.raises(SystemExit):
        cli._prepare_out(link, force=True)
    assert link.is_symlink()
    _assert_untouched(real)
