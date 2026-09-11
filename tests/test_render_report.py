"""Step 13: report IR + JSON/XLSX/PDF renderers. Uses the real committed
StatsBomb fixture (one full match) since the report touches nearly every
metric module — a synthetic warehouse would need to fake all of them.

The PDF is compiled for real here. It used to be exempt: WeasyPrint needed
system libraries this machine has no way to install, so the renderer was
checked through its template instead and had never once run.
"""

from pathlib import Path

import duckdb
import pytest

from engine.ingest.statsbomb import ingest_competition
from engine.metrics import psxg
from engine.metrics.benchmark import MIN_BENCHMARK_N
from engine.metrics.psxg import PSxGModel
from engine.model.schema import ensure_schema
from engine.render.json_renderer import render_json
from engine.render.pdf_renderer import render_pdf
from engine.render.report import build_report
from engine.render.xlsx_renderer import render_xlsx

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "statsbomb" / "data"


class _FixedProbPipeline:
    def predict_proba(self, x):
        import numpy as np
        return np.array([[0.7, 0.3] for _ in x])


@pytest.fixture(scope="module", autouse=True)
def _fake_psxg_model():
    # The fixture is one match with one goal -- too thin to train a real
    # logistic regression (same issue test_metrics_psxg.py works around).
    # The report just needs *a* model, not a validated one.
    psxg._MODEL_CACHE["9-281"] = PSxGModel(
        pipeline=_FixedProbPipeline(), n_shots=0, n_goals=0, cv_brier_score=0.0, cv_log_loss=0.0,
    )
    yield
    psxg._MODEL_CACHE.clear()


@pytest.fixture(scope="module")
def con():
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    ingest_competition(con, competition_id=9, season_id=281, data_dir=FIXTURE_DIR)
    return con


@pytest.fixture(scope="module")
def keeper_id(con):
    return con.execute(
        "select id from person where primary_position = 'Goalkeeper' limit 1"
    ).fetchone()[0]


def test_build_report_structure(con, keeper_id):
    report = build_report(con, keeper_id, "9-281", "2023/2024")
    assert report["person_id"] == keeper_id
    assert report["position_bucket"] == "GK"
    assert len(report["foundation_metrics"]) > 0
    assert report["position_panel"] is not None  # GK gets psxg_ga + defensive context
    assert {m["id"] for m in report["position_panel"]} == {
        "psxg_ga", "defensive_xg_per_shot_faced",
        "defensive_shots_central_share", "defensive_shots_unpressured_share",
    }
    assert len(report["game_state_response"]) == 3 * 5  # 3 stats x 5 buckets
    assert "StatsBomb" in report["attribution"]


def test_every_foundation_metric_carries_provenance(con, keeper_id):
    report = build_report(con, keeper_id, "9-281", "2023/2024")
    for m in report["foundation_metrics"]:
        assert m["methodology"]
        assert m["definition_version"] >= 1
        assert isinstance(m["sample_size"], int)
        assert m["suppressed"] == (m["sample_size"] < m["min_sample"])
        assert m["benchmark_suppressed"] == (m["benchmark_n"] < m["benchmark_min_n"])


def test_percentile_is_suppressed_against_a_tiny_comparison_set(con, keeper_id):
    # The fixture slice is one match, so most position buckets hold one or
    # two qualifying players. A percentile against a set that includes the
    # subject and almost nobody else is 1.00 by construction — it has to
    # come out marked, not as a confident 100th percentile.
    report = build_report(con, keeper_id, "9-281", "2023/2024")
    tiny = [m for m in report["foundation_metrics"] if m["benchmark_n"] < MIN_BENCHMARK_N]
    assert tiny, "expected at least one under-populated benchmark in this fixture"
    for m in tiny:
        assert m["benchmark_suppressed"]
        # The raw number still rides along for the JSON renderer (brief §9).
        assert "benchmark_percentile" in m

    for m in report["foundation_metrics"]:
        if m["benchmark_n"] >= MIN_BENCHMARK_N:
            assert not m["benchmark_suppressed"]


def test_xlsx_marks_a_tiny_comparison_set(con, keeper_id, tmp_path):
    report = build_report(con, keeper_id, "9-281", "2023/2024")
    out = tmp_path / "report.xlsx"
    render_xlsx(report, out)
    import zipfile
    strings = zipfile.ZipFile(out).read("xl/sharedStrings.xml").decode()
    assert "insufficient comparison set" in strings


def test_json_renderer_writes_valid_file(con, keeper_id, tmp_path):
    report = build_report(con, keeper_id, "9-281", "2023/2024")
    out = tmp_path / "report.json"
    render_json(report, out)
    import json
    reloaded = json.loads(out.read_text())
    assert reloaded["name"] == report["name"]


def test_xlsx_renderer_writes_file(con, keeper_id, tmp_path):
    report = build_report(con, keeper_id, "9-281", "2023/2024")
    out = tmp_path / "report.xlsx"
    render_xlsx(report, out)
    assert out.exists()
    assert out.stat().st_size > 0


def test_pdf_renderer_writes_a_real_pdf(con, keeper_id, tmp_path):
    # The renderer this replaced needed Pango/cairo/libgobject as system
    # libraries, never ran on this machine, and was checked only through
    # its template. Typst ships self-contained, so the PDF itself is now
    # the thing under test.
    report = build_report(con, keeper_id, "9-281", "2023/2024")
    out = tmp_path / "report.pdf"
    render_pdf(report, out)
    assert out.read_bytes()[:5] == b"%PDF-"
    assert out.stat().st_size > 10_000


def test_pdf_renders_the_goalkeeper_whose_report_is_mostly_suppressed(con, keeper_id, tmp_path):
    # The keeper bucket holds one qualifying player, so nearly every
    # benchmark is suppressed. That path has to produce a document, not a
    # crash or an empty page.
    report = build_report(con, keeper_id, "9-281", "2023/2024")
    assert report["claims"]["benchmark_suppressed_count"] > 0
    out = tmp_path / "gk.pdf"
    render_pdf(report, out)
    assert out.stat().st_size > 10_000


def test_bootstrap_metric_renders_with_its_interval(con, keeper_id, tmp_path):
    # psxg_ga declares confidence: bootstrap. The interval was being
    # computed and then dropped at render — the GK panel showed a bare
    # 0.167. Brief §6: never a bare point estimate for these.
    report = build_report(con, keeper_id, "9-281", "2023/2024")
    bootstrap = [m for m in report["position_panel"] if m["confidence"] == "bootstrap"]
    assert bootstrap, "expected the GK panel to carry a bootstrap metric"
    for m in bootstrap:
        assert m["ci_low"] is not None and m["ci_high"] is not None
        assert " to " in m["display_value"], m["display_value"]
        assert m["display_value"].endswith(")")

    # Suppression still wins: a sub-min_sample value shows its suppression
    # text, interval or not. Everything above threshold must show the
    # interval in the sheet, not a bare number.
    out = tmp_path / "r.xlsx"
    render_xlsx(report, out)
    import zipfile
    strings = zipfile.ZipFile(out).read("xl/sharedStrings.xml").decode()
    for m in bootstrap:
        expected = "insufficient sample" if m["suppressed"] else m["display_value"]
        assert expected in strings


def test_no_rendered_ordinal_exceeds_its_comparison_set(con, keeper_id):
    report = build_report(con, keeper_id, "9-281", "2023/2024")
    for m in report["foundation_metrics"]:
        comparison = m.get("benchmark_comparison")
        if comparison is None or "percentile" in comparison:
            continue
        stated = int(comparison.split()[0].rstrip("stndrh"))
        assert stated <= m["benchmark_n"], f"{m['id']}: {comparison}"


def test_every_methodology_path_resolves(con, keeper_id):
    report = build_report(con, keeper_id, "9-281", "2023/2024")
    entries = (
        report["foundation_metrics"]
        + (report["position_panel"] or [])
        + (report["throw_in_profile"] or [])
    )
    for m in entries:
        assert Path(m["methodology"]).exists(), f"{m['id']} -> {m['methodology']}"
    assert Path(report["claims"]["methodology"]).exists()
