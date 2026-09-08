"""Step 11: line_break_value. Hand-computed expected values (PHASE-0-
BRIEF.md §10) against a small synthetic warehouse. Real-data validation
against Impect's packing/packing-xG numbers is documented separately in
docs/metrics/line_break_value.md, not re-derived here."""

import json

import duckdb
import pytest

from engine.metrics import line_break, registry  # noqa: F401 (registers impl)
from engine.metrics.definitions import MetricDefinition
from engine.metrics.line_break import _bypassed_value_and_count
from engine.model.schema import ensure_schema

DEFN = MetricDefinition(
    id="line_break_value", version=1, title="t", applies_to="all", min_sample=1,
    methodology="x", adjustments=["per_90"],
)


def test_bypassed_opponent_counted_and_weighted():
    freeze_frame = [
        {"x": 60, "y": 50, "teammate": False, "actor": False, "keeper": False},
    ]
    value, count = _bypassed_value_and_count(50, 70, freeze_frame)
    assert count == 1
    assert value == pytest.approx(0.6)


def test_opponent_still_in_front_after_pass_not_bypassed():
    # Opponent at x=80: in front before (80 > 50) AND still in front after (80 > 70).
    freeze_frame = [{"x": 80, "y": 50, "teammate": False, "actor": False, "keeper": False}]
    value, count = _bypassed_value_and_count(50, 70, freeze_frame)
    assert count == 0
    assert value == 0.0


def test_opponent_already_behind_ball_not_bypassed():
    # Opponent at x=40: never in front of the ball (40 < 50) -- nothing to bypass.
    freeze_frame = [{"x": 40, "y": 50, "teammate": False, "actor": False, "keeper": False}]
    value, count = _bypassed_value_and_count(50, 70, freeze_frame)
    assert count == 0


def test_teammate_and_keeper_excluded():
    freeze_frame = [
        {"x": 60, "y": 50, "teammate": True, "actor": False, "keeper": False},
        {"x": 60, "y": 50, "teammate": False, "actor": False, "keeper": True},
    ]
    value, count = _bypassed_value_and_count(50, 70, freeze_frame)
    assert count == 0
    assert value == 0.0


def test_boundary_exactly_at_end_x_counts_as_bypassed():
    # Opponent exactly at the pass's end location: no longer strictly in
    # front (x <= end_x), so it counts.
    freeze_frame = [{"x": 70, "y": 50, "teammate": False, "actor": False, "keeper": False}]
    value, count = _bypassed_value_and_count(50, 70, freeze_frame)
    assert count == 1
    assert value == pytest.approx(0.7)


def test_multiple_opponents_summed():
    freeze_frame = [
        {"x": 55, "y": 50, "teammate": False, "actor": False, "keeper": False},  # bypassed
        {"x": 65, "y": 50, "teammate": False, "actor": False, "keeper": False},  # bypassed
        {"x": 90, "y": 50, "teammate": False, "actor": False, "keeper": False},  # not bypassed
    ]
    value, count = _bypassed_value_and_count(50, 70, freeze_frame)
    assert count == 2
    assert value == pytest.approx(0.55 + 0.65)


@pytest.fixture
def con():
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    con.execute("insert into competition values ('C1', 'Comp', NULL, NULL, 'male', 'S1')")
    con.execute("insert into team values (1, 'A', 'C1')")
    con.execute("insert into team values (2, 'B', 'C1')")
    con.execute("insert into person values (100, 'Passer', NULL, NULL, 'Center Midfield')")
    con.execute("insert into fixture values (11, 'C1', 1, 2, NULL)")
    con.execute("insert into appearance values (11, 100, 1, 90, 0, 90)")

    def insert(seq, outcome, loc_x, end_x, freeze_frame):
        con.execute(
            "insert into event values (11, ?, ?, 1, 'PASS', 100, 1, ?, 50, ?, 50, NULL, ?, NULL, ?, NULL, ?)",
            [seq, seq * 1000, loc_x, end_x, outcome, None, json.dumps(freeze_frame)],
        )

    # Pass 1: bypasses one opponent (value 0.6).
    insert(0, "COMPLETE", 50, 70, [{"x": 60, "y": 50, "teammate": False, "actor": False, "keeper": False}])
    # Pass 2: bypasses nobody (backward pass).
    insert(1, "COMPLETE", 70, 50, [{"x": 60, "y": 50, "teammate": False, "actor": False, "keeper": False}])
    # Pass 3: incomplete -- excluded regardless of freeze frame.
    insert(2, "INCOMPLETE", 50, 70, [{"x": 60, "y": 50, "teammate": False, "actor": False, "keeper": False}])
    # Pass 4: no freeze frame at all -- excluded.
    con.execute(
        "insert into event values (11, 3, 3000, 1, 'PASS', 100, 1, 50, 50, 70, 50, NULL, 'COMPLETE', NULL, NULL, NULL, 'null')"
    )
    return con


def test_passes_with_value_filters_correctly(con):
    passes = line_break._passes_with_value(con, 100, "C1")
    assert len(passes) == 2  # only the two COMPLETE passes with a real freeze frame
    assert passes[0] == (pytest.approx(0.6), 1)
    assert passes[1] == (0.0, 0)


def test_line_break_value_raw_and_per90(con):
    impl = registry.get_implementation("line_break_value")
    raw = impl(con, DEFN, person_id=100, competition_id="C1", season="S1", adjustment="raw")
    assert raw.value == pytest.approx(0.6)
    assert raw.sample_size == 2

    per90 = impl(con, DEFN, person_id=100, competition_id="C1", season="S1", adjustment="per_90")
    assert per90.value == pytest.approx(0.6)  # 90 minutes = 1.0x


def test_unsupported_adjustment_raises(con):
    impl = registry.get_implementation("line_break_value")
    with pytest.raises(ValueError, match="unknown adjustment"):
        impl(con, DEFN, person_id=100, competition_id="C1", season="S1", adjustment="possession")
