"""Step 7: benchmark sets — position bucketing, the roster batch driver,
and stored distributions. Hand-computed expected values against a small
synthetic warehouse (PHASE-0-BRIEF.md §10)."""

import json
from datetime import datetime, timezone

import duckdb
import pytest

from engine.metrics import benchmark, foundation, registry  # noqa: F401 (foundation registers impls)
from engine.metrics.benchmark import (
    compute_benchmark,
    compute_roster_metrics,
    percentile_rank,
    position_bucket,
    roster_person_ids,
)
from engine.metrics.definitions import MetricDefinition
from engine.model.schema import ensure_schema

SHOTS_DEFN = MetricDefinition(
    id="shots", version=1, title="t", applies_to="all", min_sample=450,
    methodology="x", adjustments=["per_90", "possession", "opposition_strength"],
)
RATIO_DEFN = MetricDefinition(
    id="pass_completion_defensive_third", version=1, title="t", applies_to="all",
    min_sample=20, methodology="x", adjustments=[],
)


@pytest.mark.parametrize(
    "raw_position, expected_bucket",
    [
        ("Goalkeeper", "GK"),
        ("Center Back", "DF"),
        ("Right Wing Back", "DF"),
        ("Center Defensive Midfield", "MF"),
        ("Left Attacking Midfield", "MF"),
        ("Center Forward", "FW"),
        ("Left Wing", "FW"),
        (None, "Unknown"),
        ("Some Future StatsBomb Label", "Unknown"),
    ],
)
def test_position_bucket(raw_position, expected_bucket):
    assert position_bucket(raw_position) == expected_bucket


def test_percentile_rank():
    dist = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile_rank(dist, 3.0) == pytest.approx(0.6)  # 3 of 5 <= 3.0
    assert percentile_rank(dist, 0.5) == pytest.approx(0.0)
    assert percentile_rank(dist, 5.0) == pytest.approx(1.0)
    assert percentile_rank([], 1.0) != percentile_rank([], 1.0)  # nan


@pytest.fixture
def con():
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    con.execute("insert into competition values ('C1', 'Comp', NULL, NULL, 'male', 'S1')")
    con.execute("insert into team values (1, 'A', 'C1')")
    return con


def _insert_metric_value(con, person_id, value, sample_size, adjustment="per_90",
                          definition_id="shots", version=1, computed_at=None):
    con.execute(
        "insert into metric_value values (?, NULL, 'C1', 'S1', ?, ?, ?, NULL, ?, ?, NULL, NULL, ?, 'h')",
        [
            person_id, definition_id, version, adjustment, value, sample_size,
            computed_at or datetime.now(timezone.utc),
        ],
    )


@pytest.fixture
def benchmark_con(con):
    roster = [
        (100, "GK1", "Goalkeeper", 0.1, 500),
        (101, "DF1", "Center Back", 0.2, 500),
        (102, "DF2", "Left Back", 0.3, 100),  # below min_sample -> excluded
        (103, "MF1", "Center Attacking Midfield", 0.5, 600),
        (104, "FW1", "Center Forward", 1.0, 700),
        (105, "FW2", "Left Wing", 1.5, 800),
        (106, "FW3", None, 2.0, 900),  # Unknown bucket
    ]
    for person_id, name, position, value, sample_size in roster:
        con.execute("insert into person values (?, ?, NULL, NULL, ?)", [person_id, name, position])
        _insert_metric_value(con, person_id, value, sample_size)
    return con


def test_compute_benchmark_filters_by_bucket_and_min_sample(benchmark_con):
    result = compute_benchmark(benchmark_con, SHOTS_DEFN, "C1", "S1", "FW", adjustment="per_90")
    assert result == {"n": 2, "values": [1.0, 1.5]}

    df_result = compute_benchmark(benchmark_con, SHOTS_DEFN, "C1", "S1", "DF", adjustment="per_90")
    assert df_result == {"n": 1, "values": [0.2]}  # DF2 excluded: sample_size 100 < 450


def test_compute_benchmark_stores_snapshot_row(benchmark_con):
    compute_benchmark(benchmark_con, SHOTS_DEFN, "C1", "S1", "GK", adjustment="per_90")
    row = benchmark_con.execute(
        "select position_bucket, definition_id, n, sample_values from benchmark_distribution"
    ).fetchone()
    assert row[0] == "GK"
    assert row[1] == "shots"
    assert row[2] == 1
    assert json.loads(row[3]) == [0.1]


def test_compute_benchmark_uses_latest_computed_at(benchmark_con):
    # FW1 gets a later, different value -> distribution should use the new
    # one only, not both (append-only ledger, "latest wins").
    _insert_metric_value(benchmark_con, 104, 1.2, 750,
                          computed_at=datetime.now(timezone.utc).replace(year=2030))
    result = compute_benchmark(benchmark_con, SHOTS_DEFN, "C1", "S1", "FW", adjustment="per_90")
    assert result == {"n": 2, "values": [1.2, 1.5]}


def test_compute_benchmark_respects_adjustment(benchmark_con):
    # A 'possession' row for FW1 must not leak into the 'per_90' distribution.
    _insert_metric_value(benchmark_con, 104, 99.0, 700, adjustment="possession")
    per90 = compute_benchmark(benchmark_con, SHOTS_DEFN, "C1", "S1", "FW", adjustment="per_90")
    assert per90 == {"n": 2, "values": [1.0, 1.5]}
    possession = compute_benchmark(benchmark_con, SHOTS_DEFN, "C1", "S1", "FW", adjustment="possession")
    assert possession == {"n": 1, "values": [99.0]}


# --- roster batch driver ----------------------------------------------------

@pytest.fixture
def roster_con(con):
    con.execute("insert into person values (200, 'P1', NULL, NULL, 'Center Forward')")
    con.execute("insert into person values (201, 'P2', NULL, NULL, 'Goalkeeper')")
    con.execute("insert into fixture values (1, 'C1', 1, 1, NULL)")
    con.execute("insert into appearance values (1, 200, 1, 90, 0, 90)")
    con.execute("insert into appearance values (1, 201, 1, 90, 0, 90)")
    con.execute(
        "insert into event values (1, 0, 0, 1, 'SHOT', 200, 1, 50, 50, NULL, NULL, NULL, "
        "'OFF_TARGET', NULL, NULL, NULL, NULL)"
    )
    con.execute(
        "insert into event values (1, 1, 1000, 1, 'PASS', 201, 1, 10, 50, 15, 50, NULL, "
        "'COMPLETE', NULL, NULL, NULL, NULL)"
    )
    return con


def test_roster_person_ids(roster_con):
    assert sorted(roster_person_ids(roster_con, "C1")) == [200, 201]


def test_compute_roster_metrics_stores_rows_for_every_player(roster_con):
    definitions = {"shots": SHOTS_DEFN, "pass_completion_defensive_third": RATIO_DEFN}
    compute_roster_metrics(roster_con, definitions, "C1", "S1", adjustment="per_90")

    rows = roster_con.execute(
        "select person_id, definition_id, adjustment, value from metric_value order by person_id, definition_id"
    ).fetchall()
    assert len(rows) == 4  # 2 players x 2 metrics

    shots_rows = {r[0]: r for r in rows if r[1] == "shots"}
    assert shots_rows[200][2] == "per_90"  # count metric gets the requested adjustment
    assert shots_rows[200][3] == pytest.approx(1.0)  # 1 shot / (90/90)

    ratio_rows = {r[0]: r for r in rows if r[1] == "pass_completion_defensive_third"}
    assert ratio_rows[201][2] is None  # ratio metric always gets adjustment=None
