"""Step 8: psxg_ga and defensive context. Hand-computed expected values
against a small synthetic warehouse (PHASE-0-BRIEF.md §10) — the real
model is trained and validated separately against the actual warehouse
(see docs/metrics/psxg_ga.md for that validation report), not here.
"""

import json
import math

import duckdb
import pytest

from engine.metrics import psxg
from engine.metrics.definitions import MetricDefinition
from engine.metrics.psxg import (
    GOAL_CENTER_Y,
    GOAL_X,
    POST_Y_HIGH,
    POST_Y_LOW,
    PSxGModel,
    _angle_to_goal,
    _extract_features,
    _traffic_count,
)
from engine.model.schema import ensure_schema

PSXG_GA_DEFN = MetricDefinition(
    id="psxg_ga", version=1, title="t", applies_to="goalkeeper", min_sample=40,
    methodology="x", adjustments=["per_90"], confidence="bootstrap",
)
DEFENSIVE_DEFN = MetricDefinition(
    id="defensive_xg_per_shot_faced", version=1, title="t", applies_to="goalkeeper",
    min_sample=40, methodology="x",
)


# --- pure geometry helpers ---------------------------------------------------

def test_angle_to_goal_maximal_on_the_goal_line():
    # Standing right on the line: the goal mouth spans a full 180 degrees.
    assert _angle_to_goal(GOAL_X, GOAL_CENTER_Y) == pytest.approx(math.pi)


def test_angle_to_goal_matches_formula_from_distance():
    x, y = 50.0, 50.0
    a1 = math.atan2(POST_Y_LOW - y, GOAL_X - x)
    a2 = math.atan2(POST_Y_HIGH - y, GOAL_X - x)
    expected = abs(a1 - a2)
    assert _angle_to_goal(x, y) == pytest.approx(expected)


def test_traffic_count_excludes_keeper_actor_and_off_line_players():
    freeze_frame = [
        {"x": 60, "y": 50, "teammate": False, "actor": False, "keeper": False},  # directly ahead: counts
        {"x": 10, "y": 50, "teammate": True, "actor": False, "keeper": False},  # behind shooter: excluded
        {"x": 60, "y": 20, "teammate": False, "actor": False, "keeper": False},  # far off-line: excluded
        {"x": 99, "y": 50, "teammate": False, "actor": False, "keeper": True},  # keeper: always excluded
        {"x": 20, "y": 50, "teammate": True, "actor": True, "keeper": False},  # shooter: always excluded
    ]
    assert _traffic_count(20, 50, freeze_frame) == 1


def _row(location_x=20.0, location_y=50.0, end_y=50.0, end_z=20.0, outcome="SAVED",
         body_part="RIGHT_FOOT", keeper_x=99.0, keeper_y=50.0, has_keeper=True):
    freeze_frame = []
    if has_keeper:
        freeze_frame.append(
            {"x": keeper_x, "y": keeper_y, "teammate": False, "actor": False, "keeper": True}
        )
    qualifiers = {"BodyPart": body_part}
    return (
        1, 0, 2, None, location_x, location_y, 90.0, end_y, end_z, outcome,
        json.dumps(qualifiers), json.dumps(freeze_frame),
    )


def test_extract_features_missing_keeper_returns_none():
    assert _extract_features(_row(has_keeper=False)) is None


def test_extract_features_missing_end_z_returns_none():
    assert _extract_features(_row(end_z=None)) is None


def test_extract_features_handles_json_null_freeze_frame_and_qualifiers():
    # Regression: real ingest stores json.dumps(None) as the *string* "null"
    # (truthy in Python) when a shot has no freeze frame / no qualifiers at
    # all — an `if x else default` guard on the raw column never catches
    # this and crashes on json.loads("null") -> None. Must return None
    # cleanly (no keeper -> excluded from training/scoring), not raise.
    row = (1, 0, 2, None, 20.0, 50.0, 90.0, 50.0, 20.0, "SAVED", "null", "null")
    assert _extract_features(row) is None


def test_extract_features_hand_checked_values():
    features = _extract_features(_row(
        location_x=20.0, location_y=50.0, end_y=55.0, end_z=20.0,
        outcome="GOAL", body_part="HEAD", keeper_x=95.0, keeper_y=48.0,
    ))
    assert features["is_goal"] == 1.0
    assert features["is_header"] == 1.0
    assert features["is_other_body_part"] == 0.0
    assert features["end_y_from_center"] == pytest.approx(5.0)  # |55 - 50|
    assert features["end_z"] == 20.0
    assert features["keeper_lateral_offset"] == pytest.approx(7.0)  # |48 - 55|
    assert features["keeper_depth"] == 95.0
    assert features["distance_to_goal"] == pytest.approx(math.hypot(80, 0))


# --- psxg_ga: aggregation + bootstrap, with a fixed-probability fake model --

class _FixedProbPipeline:
    def __init__(self, prob):
        self.prob = prob

    def predict_proba(self, x):
        import numpy as np
        return np.array([[1 - self.prob, self.prob] for _ in x])


@pytest.fixture
def con():
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    con.execute("insert into competition values ('C1', 'Comp', NULL, NULL, 'male', 'S1')")
    con.execute("insert into team values (1, 'A', 'C1')")
    con.execute("insert into team values (2, 'B', 'C1')")
    con.execute("insert into person values (100, 'Keeper', NULL, NULL, 'Goalkeeper')")
    con.execute("insert into fixture values (11, 'C1', 1, 2, NULL)")
    con.execute("insert into appearance values (11, 100, 1, 90, 0, 90)")

    # 3 shots faced by team A's keeper, from team B: 2 saved, 1 goal.
    for seq, outcome in enumerate(["SAVED", "SAVED", "GOAL"]):
        row = _row(outcome=outcome)
        con.execute(
            "insert into event values (?, ?, ?, ?, 'SHOT', NULL, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?)",
            [11, seq, seq * 1000, 1, row[2], row[4], row[5], row[6], row[7], row[8], row[9],
             row[10], row[11]],
        )
    return con


@pytest.fixture(autouse=True)
def _clear_model_cache():
    yield
    psxg._MODEL_CACHE.clear()


def test_psxg_ga_raw_and_per90(con):
    psxg._MODEL_CACHE["C1"] = PSxGModel(
        pipeline=_FixedProbPipeline(0.3), n_shots=3, n_goals=1, cv_brier_score=0.0, cv_log_loss=0.0,
    )
    raw = psxg._psxg_ga_impl(con, PSXG_GA_DEFN, person_id=100, competition_id="C1",
                              season="S1", adjustment="raw")
    # 3 shots at PSxG 0.3 each = 0.9 total; 1 goal conceded -> 0.9 - 1 = -0.1
    assert raw.value == pytest.approx(-0.1)
    assert raw.sample_size == 3

    per90 = psxg._psxg_ga_impl(con, PSXG_GA_DEFN, person_id=100, competition_id="C1",
                                season="S1", adjustment="per_90")
    assert per90.value == pytest.approx(-0.1 / 1.0)  # 90 minutes = 1.0x


def test_psxg_ga_bootstrap_ci_present_and_sane(con):
    psxg._MODEL_CACHE["C1"] = PSxGModel(
        pipeline=_FixedProbPipeline(0.3), n_shots=3, n_goals=1, cv_brier_score=0.0, cv_log_loss=0.0,
    )
    result = psxg._psxg_ga_impl(con, PSXG_GA_DEFN, person_id=100, competition_id="C1",
                                 season="S1", adjustment="per_90")
    assert result.ci_low is not None and result.ci_high is not None
    assert result.ci_low <= result.value <= result.ci_high


def test_psxg_ga_unsupported_adjustment_raises(con):
    psxg._MODEL_CACHE["C1"] = PSxGModel(
        pipeline=_FixedProbPipeline(0.3), n_shots=3, n_goals=1, cv_brier_score=0.0, cv_log_loss=0.0,
    )
    with pytest.raises(ValueError, match="unknown adjustment"):
        psxg._psxg_ga_impl(con, PSXG_GA_DEFN, person_id=100, competition_id="C1",
                            season="S1", adjustment="possession")


# --- defensive context -------------------------------------------------------

@pytest.fixture
def defensive_con(con):
    # 3 more shots, with known xG/pressure/zone to hand-verify each metric.
    shots = [
        dict(seq=10, location_y=50.0, xg=0.2, under_pressure=False),  # central, unpressured
        dict(seq=11, location_y=10.0, xg=0.4, under_pressure=True),  # wide, pressured
        dict(seq=12, location_y=90.0, xg=0.6, under_pressure=False),  # wide, unpressured
    ]
    for s in shots:
        qualifiers = {"BodyPart": "RIGHT_FOOT", "xG": s["xg"]}
        if s["under_pressure"]:
            qualifiers["UnderPressure"] = True
        freeze_frame = [{"x": 99, "y": 50, "teammate": False, "actor": False, "keeper": True}]
        con.execute(
            "insert into event values (?, ?, ?, ?, 'SHOT', NULL, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?)",
            [11, s["seq"], s["seq"] * 1000, 1, 2, 20.0, s["location_y"], 90.0, s["location_y"],
             20.0, "SAVED", json.dumps(qualifiers), json.dumps(freeze_frame)],
        )
    return con


def test_defensive_context_handles_json_null_qualifiers(con):
    # Regression: a shot with no qualifiers at all stores qualifiers as the
    # JSON string "null", not SQL NULL. Must not crash, and correctly
    # excludes from mean_xg (no xG key) while counting as unpressured (no
    # UnderPressure key) and toward sample_size.
    con.execute(
        "insert into event values (?, ?, ?, ?, 'SHOT', NULL, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?)",
        [11, 99, 99000, 1, 2, 20.0, 50.0, 90.0, 50.0, 20.0, "SAVED", "null",
         json.dumps([{"x": 99, "y": 50, "teammate": False, "actor": False, "keeper": True}])],
    )
    mean_xg = psxg._make_defensive_context_impl("mean_xg")(
        con, DEFENSIVE_DEFN, person_id=100, competition_id="C1", season="S1"
    )
    assert mean_xg.sample_size == 4  # 3 from `con` fixture + this one
    assert mean_xg.value is None  # none of those 4 rows carry an xG qualifier

    unpressured = psxg._make_defensive_context_impl("unpressured_share")(
        con, DEFENSIVE_DEFN, person_id=100, competition_id="C1", season="S1"
    )
    assert unpressured.value == pytest.approx(100.0)  # none flagged under pressure


def test_defensive_xg_per_shot_faced(defensive_con):
    result = psxg._make_defensive_context_impl("mean_xg")(
        defensive_con, DEFENSIVE_DEFN, person_id=100, competition_id="C1", season="S1"
    )
    # 6 shots total faced now (3 from `con` with no xG set, 3 from `defensive_con` with xG).
    # Only rows carrying an xG qualifier count toward the mean.
    assert result.value == pytest.approx((0.2 + 0.4 + 0.6) / 3)
    assert result.sample_size == 6


def test_defensive_shots_central_share(defensive_con):
    result = psxg._make_defensive_context_impl("central_share")(
        defensive_con, DEFENSIVE_DEFN, person_id=100, competition_id="C1", season="S1"
    )
    # Of 6 shots faced, location_y in [30,70]: the 3 original (y=50) + 1 new (y=50) = 4/6.
    assert result.value == pytest.approx(100 * 4 / 6)


def test_defensive_shots_unpressured_share(defensive_con):
    result = psxg._make_defensive_context_impl("unpressured_share")(
        defensive_con, DEFENSIVE_DEFN, person_id=100, competition_id="C1", season="S1"
    )
    # 5 of 6 shots faced have no UnderPressure qualifier (only 1 of the 3 new ones is pressured).
    assert result.value == pytest.approx(100 * 5 / 6)
