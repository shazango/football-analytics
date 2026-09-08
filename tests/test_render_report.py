"""Step 13: report IR + JSON/XLSX renderers. Uses the real committed
StatsBomb fixture (one full match) since the report touches nearly every
metric module — a synthetic warehouse would need to fake all of them.
PDF isn't tested here: WeasyPrint is unavailable on this dev machine
(see engine/render/pdf_renderer.py); the Jinja2 template itself is
exercised directly (no WeasyPrint needed) to catch template bugs.
"""

from pathlib import Path

import duckdb
import jinja2
import pytest

from engine.ingest.statsbomb import ingest_competition
from engine.metrics import psxg
from engine.metrics.psxg import PSxGModel
from engine.model.schema import ensure_schema
from engine.render.json_renderer import render_json
from engine.render.report import build_report
from engine.render.xlsx_renderer import render_xlsx

TEMPLATE_DIR = Path(__file__).parent.parent / "src" / "engine" / "render" / "templates"

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


def test_pdf_template_renders_without_weasyprint(con, keeper_id):
    # Exercises the Jinja2 template directly -- catches template bugs
    # (undefined vars, bad loops) without needing WeasyPrint installed.
    report = build_report(con, keeper_id, "9-281", "2023/2024")
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    html = env.get_template("report.html").render(report=report)
    assert report["name"] in html
    assert "Foundation metrics" in html
