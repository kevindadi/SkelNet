"""T7: the generated LaTeX keeps the paper placeholder layout."""

import importlib.util
import re
from pathlib import Path

import pytest

from skelnet import report

FIXTURES = Path(__file__).parent / "fixtures" / "round08"
PAPER = FIXTURES / "paper_tables"
_spec = importlib.util.spec_from_file_location("r8synth", FIXTURES / "synth.py")
synth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(synth)

TABLES = {
    "main": "main.tex", "tiers": "tiers.tex", "design": "ingredients.tex",
    "failures": "failures.tex", "cost": "cost.tex", "models": "models.tex",
    "benchmark": "benchmark.tex",
}


@pytest.fixture(scope="module")
def planted(tmp_path_factory):
    root = tmp_path_factory.mktemp("planted")
    synth.make_runs(root, synth.planted_spec())
    synth.write_fake_tasks(root, synth.planted_spec()["tasks"])
    runs = sorted(p for p in root.glob("*/*") if (p / "MANIFEST.json").exists())
    ctx = report.ReportContext(root=root, look=2, bootstrap=2000, seed=1)
    ds, payloads = report.build_report(runs, ctx, list(report.ALL_TABLES),
                                       figure=True)
    return ds, payloads, ctx


def _tabular(text: str):
    lines = [line.rstrip() for line in text.splitlines()]
    start = next(i for i, line in enumerate(lines)
                 if line.startswith("\\begin{tabular}"))
    end = next(i for i, line in enumerate(lines)
               if line.strip() == "\\end{tabular}")
    colspec = lines[start].strip()
    body = lines[start + 1:end]
    markers = [line.strip() for line in body
               if line.strip() in ("\\midrule", "\\addlinespace", "\\bottomrule")]
    first_marker = next(i for i, line in enumerate(body)
                        if line.strip() == "\\midrule")
    header = [line.strip() for line in body[:first_marker]]
    rows = []
    footnotes = []
    for line in body[first_marker + 1:]:
        stripped = line.strip()
        if stripped in ("\\midrule", "\\addlinespace", "\\bottomrule"):
            continue
        if not stripped:
            continue
        if stripped.startswith("\\multicolumn"):
            footnotes.append(stripped)
            continue
        rows.append(stripped)
    return colspec, header, markers, rows, footnotes


def _label(row: str) -> str:
    return row.split("&")[0].strip()


def _segments(text: str):
    return [part for part in re.split(r"\\PH(?:\[3 or 4\])?", text) if part]


@pytest.mark.parametrize("name", sorted(TABLES))
def test_placeholder_layout(name, planted):
    ds, payloads, ctx = planted
    generated = report.TEX_RENDERERS[name](payloads[name], ds, ctx)
    placeholder = (PAPER / TABLES[name]).read_text(encoding="utf-8")
    g_col, g_head, g_mark, g_rows, g_foot = _tabular(generated)
    p_col, p_head, p_mark, p_rows, p_foot = _tabular(placeholder)
    assert g_col == p_col
    assert g_head == p_head
    assert g_mark == p_mark
    assert len(g_rows) == len(p_rows)
    for grow, prow in zip(g_rows, p_rows):
        assert _label(grow) == _label(prow)
        assert grow.count("&") == prow.count("&")
    assert len(g_foot) == len(p_foot)
    for gline, pline in zip(g_foot, p_foot):
        segments = _segments(pline)
        position = 0
        for segment in segments:
            found = gline.find(segment, position)
            assert found >= 0, (segment, gline)
            position = found + len(segment)


def test_no_placeholders_or_absolute_paths(planted):
    ds, payloads, ctx = planted
    for name in report.ALL_TABLES:
        text = report.TEX_RENDERERS[name](payloads[name], ds, ctx)
        assert "\\PH" not in text and "\\TODO" not in text
        assert "/tmp" not in text and "/home" not in text
        assert "/Users" not in text
    anytime = report.render_anytime_tex(payloads["anytime"], ds, ctx)
    assert "\\PH" not in anytime and "\\TODO" not in anytime


def test_anytime_keeps_the_axes_and_colours(planted):
    ds, payloads, ctx = planted
    text = report.render_anytime_tex(payloads["anytime"], ds, ctx)
    assert "x=12mm, y=24mm" in text
    assert "\\foreach \\b in {1,...,5}" in text
    assert "\\foreach \\y/\\l in {0/0,0.5/50\\%,1/100\\%}" in text
    for color in ("CPVBlue", "CPVTeal", "gray", "gray!70", "gray!50",
                  "CPVWarn", "CPVWarn!60"):
        assert color in text
    assert "PhBack" not in text


def test_tiny_main_matches_the_committed_golden():
    runs = sorted(p for p in (FIXTURES / "tiny").glob("*/*")
                  if (p / "MANIFEST.json").exists())
    ctx = report.ReportContext(root=FIXTURES / "tiny", look=2)
    ds, payloads = report.build_report(runs, ctx, ["main"])
    generated = report.TEX_RENDERERS["main"](payloads["main"], ds, ctx)
    golden = (FIXTURES / "tiny" / "main.golden.tex").read_text(encoding="utf-8")
    assert generated == golden


def test_tiny_golden_numbers_match_expected_md():
    golden = (FIXTURES / "tiny" / "main.golden.tex").read_text(encoding="utf-8")
    expected = (FIXTURES / "tiny" / "EXPECTED.md").read_text(encoding="utf-8")
    # Values that are hand-derived in EXPECTED.md and must appear in the golden.
    for value in ("72.2", "52.9", "50.0", "77.8", "64.7", "61.1", "23.5",
                  "22.2", "27.8"):
        assert value in golden
    assert "72.2" in expected and "23.5" in expected
