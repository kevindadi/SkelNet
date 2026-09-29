"""B5: O3 wrong_output / livelock are valid expect.json categories."""

import json

import pytest

from test_bench_validate import _check, make_task


def _expect(task, spec):
    (task / "rust" / "expect.json").write_text(json.dumps({
        "schema_version": "skelnet-rust-expect-v1",
        "fixed.rs": {"functional": True},
        "buggy.rs": spec,
    }), encoding="utf-8")


def _factory(category):
    def factory(task_dir, terminal):
        class Oracle:
            def evaluate(self, source, workdir):
                ok = 'println!("{}", 0)' not in source
                layer = type("L", (), {"status": "fail", "category": category})()
                return type("R", (), {"functional_ok": ok, "layers": {"O3": layer}})()
        return Oracle()
    return factory


@pytest.mark.parametrize("category", ["wrong_output", "livelock"])
def test_new_o3_categories_are_accepted(tmp_path, category):
    root = tmp_path / "repo"
    task = make_task(root)
    _expect(task, {"functional": False, "layer": "O3", "category": category})
    result = _check(root, "fam/task", "V8", oracle=True,
                    oracle_factory=_factory(category))
    assert result["status"] == "pass", result
    assert f"buggy.rs O3/{category}" in result["reason"]


@pytest.mark.parametrize("category", ["hang", "no_output", "monitor_fail"])
def test_other_layers_categories_stay_invalid_for_o3(tmp_path, category):
    root = tmp_path / "repo"
    task = make_task(root)
    _expect(task, {"functional": False, "layer": "O3", "category": category})
    result = _check(root, "fam/task", "V8", oracle=True,
                    oracle_factory=_factory(category))
    assert result["status"] == "fail"
    assert f"category {category} is not valid for O3" in result["reason"]
