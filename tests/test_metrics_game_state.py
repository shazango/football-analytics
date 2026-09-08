"""Step 12: game_state_response. Hand-computed expected values (PHASE-0-
BRIEF.md §10) against a small synthetic warehouse with a clean, known
score-state timeline.

Naming discipline (brief §7.6): the word "morale" must never appear here.
"""

import duckdb
import pytest

from engine.metrics import foundation, game_state, registry  # noqa: F401 (registers impls)
from engine.metrics.definitions import MetricDefinition
from engine.model.schema import ensure_schema

SHOTS_DEFN = MetricDefinition(
    id="shots", version=1, title="t", applies_to="all", min_sample=1, methodology="x",
    adjustments=["per_90"],
    game_state_buckets=["leading", "level", "trailing_1", "trailing_2plus", "after_conceding_10min"],
)
PRESSING_DEFN = MetricDefinition(
    id="game_state_pressing_intensity_trailing_2plus", version=1, title="t",
    applies_to="all", min_sample=1, methodology="x",
)


def _insert(con, seq, team, type_, minute, outcome=None, actor=None, qualifiers=None, game_state_val=None):
    con.execute(
        "insert into event values (?, ?, ?, 1, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, ?, NULL, ?, ?, NULL)",
        [11, seq, minute * 60000, type_, actor, team, outcome,
         __import__("json").dumps(qualifiers) if qualifiers else None, game_state_val],
    )


@pytest.fixture
def con():
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    con.execute("insert into competition values ('C1', 'Comp', NULL, NULL, 'male', 'S1')")
    con.execute("insert into team values (1, 'A', 'C1')")
    con.execute("insert into team values (2, 'B', 'C1')")
    con.execute("insert into person values (100, 'Player', NULL, NULL, 'Center Forward')")
    con.execute("insert into person values (999, 'TeamAScorer', NULL, NULL, 'Center Forward')")
    con.execute("insert into person values (998, 'TeamBScorer', NULL, NULL, 'Center Forward')")
    con.execute("insert into fixture values (11, 'C1', 1, 2, NULL)")
    con.execute("insert into appearance values (11, 100, 1, 90, 0, 90)")

    seq = 0
    # Timeline (team A's own margin): B scores at 10' (-1), B scores again
    # at 20' (-2, trailing_2plus starts), A scores at 30' (-1), A scores at
    # 40' (0, level), A scores at 50' (+1, leading). Segments:
    # [0,10) level, [10,20) trailing_1, [20,30) trailing_2plus,
    # [30,40) trailing_1, [40,50) level, [50,90) leading.
    for minute, team in [(10, 2), (20, 2)]:
        _insert(con, seq, team, "SHOT", minute, outcome="GOAL", actor=998); seq += 1
    for minute, team in [(30, 1), (40, 1), (50, 1)]:
        _insert(con, seq, team, "SHOT", minute, outcome="GOAL", actor=999); seq += 1

    # Player 100's shots, one batch per segment, with game_state set as it
    # would be by the real ingest pipeline (step 3) for team 1's own events.
    shots = [
        (5, "0", 1),    # level
        (15, "-1", 2),  # trailing_1
        (25, "-2", 1),  # trailing_2plus
        (35, "-1", 1),  # trailing_1
        (45, "0", 1),   # level
        (60, "1", 3),   # leading
    ]
    for minute, state, count in shots:
        for _ in range(count):
            _insert(con, seq, 1, "SHOT", minute, outcome="OFF_TARGET", actor=100, game_state_val=state)
            seq += 1

    # Pressing-intensity fixture data: within the trailing_2plus window
    # [20,30), team B completes 4 passes and team A records 2 defensive
    # actions (1 interception, 1 won tackle).
    for minute in (22, 24, 26, 28):
        _insert(con, seq, 2, "PASS", minute, outcome="COMPLETE"); seq += 1
    _insert(con, seq, 1, "INTERCEPTION", 23); seq += 1
    _insert(con, seq, 1, "DUEL", 27, outcome="WON", qualifiers={"Duel": "TACKLE"}); seq += 1

    return con


def test_minutes_by_margin_bucket(con):
    minutes = game_state.minutes_by_margin_bucket(con, 100, "C1")
    assert minutes == {"level": pytest.approx(20.0), "trailing_1": pytest.approx(20.0),
                        "trailing_2plus": pytest.approx(10.0), "leading": pytest.approx(40.0)}
    assert sum(minutes.values()) == pytest.approx(90.0)


def test_state_scoped_shots_raw_counts_per_bucket(con):
    impl = registry.get_implementation("shots")
    expected_raw = {"level": 2, "trailing_1": 3, "trailing_2plus": 1, "leading": 3}
    for bucket, raw in expected_raw.items():
        result = impl(con, SHOTS_DEFN, person_id=100, competition_id="C1", season="S1",
                       adjustment="raw", game_state_bucket=bucket)
        assert result.value == raw, bucket


def test_state_scoped_shots_per90(con):
    impl = registry.get_implementation("shots")
    # per90 = raw / (bucket_minutes / 90)
    expected_per90 = {
        "level": 2 / (20 / 90),
        "trailing_1": 3 / (20 / 90),
        "trailing_2plus": 1 / (10 / 90),
        "leading": 3 / (40 / 90),
    }
    for bucket, expected in expected_per90.items():
        result = impl(con, SHOTS_DEFN, person_id=100, competition_id="C1", season="S1",
                       adjustment="per_90", game_state_bucket=bucket)
        assert result.value == pytest.approx(expected), bucket


def test_state_scoped_delegates_to_original_when_no_bucket(con):
    # game_state_bucket=None must reproduce foundation.py's own (unwrapped)
    # whole-season behaviour exactly -- this is the core safety property
    # of the delegating-wrapper design (no regression to step 6).
    wrapped = registry.get_implementation("shots")(
        con, SHOTS_DEFN, person_id=100, competition_id="C1", season="S1", adjustment="per_90"
    )
    original = foundation._make_count_impl("shots")(
        con, definition=SHOTS_DEFN, person_id=100, competition_id="C1", season="S1", adjustment="per_90"
    )
    assert wrapped == original


def test_after_conceding_10min_window(con):
    # Windows [10,20) and [20,30) minutes (10 min after each goal B
    # scores). Shots at 15' (2) and 25' (1) fall inside -> 3 total, over
    # 20 minutes on the pitch during those windows.
    impl = registry.get_implementation("shots")
    raw = impl(con, SHOTS_DEFN, person_id=100, competition_id="C1", season="S1",
               adjustment="raw", game_state_bucket="after_conceding_10min")
    assert raw.value == 3

    per90 = impl(con, SHOTS_DEFN, person_id=100, competition_id="C1", season="S1",
                 adjustment="per_90", game_state_bucket="after_conceding_10min")
    assert per90.value == pytest.approx(3 / (20 / 90))


def test_unsupported_bucket_raises(con):
    bare = MetricDefinition(id="shots", version=1, title="t", applies_to="all",
                             min_sample=1, methodology="x", adjustments=["per_90"],
                             game_state_buckets=[])
    impl = registry.get_implementation("shots")
    with pytest.raises(ValueError, match="does not declare support"):
        impl(con, bare, person_id=100, competition_id="C1", season="S1",
             adjustment="per_90", game_state_bucket="leading")


def test_pressing_intensity_trailing_2plus(con):
    result = game_state._pressing_intensity_impl(
        con, PRESSING_DEFN, person_id=100, competition_id="C1", season="S1"
    )
    assert result.value == pytest.approx(4 / 2)  # 4 opponent passes / 2 defensive actions
    assert result.sample_size == 2


def test_pressing_intensity_no_trailing_2plus_returns_none(con):
    con.execute("insert into person values (200, 'Other', NULL, NULL, 'Center Back')")
    con.execute("insert into fixture values (12, 'C1', 1, 2, NULL)")
    con.execute("insert into appearance values (12, 200, 1, 90, 0, 90)")
    # No goals at all in fixture 12 -> no trailing_2plus window ever occurs.
    result = game_state._pressing_intensity_impl(
        con, PRESSING_DEFN, person_id=200, competition_id="C1", season="S1"
    )
    assert result.value is None
    assert result.sample_size == 0
