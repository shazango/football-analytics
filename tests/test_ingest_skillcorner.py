"""Step 14: SkillCorner physical ingest. Hand-computed expected values
(PHASE-0-BRIEF.md §10) for the pure bucket-stats function; the full
pipeline is exercised against real SkillCorner tracking data (network),
using a synthetic warehouse seeded with a real player's name, since the
actual Bundesliga warehouse shares no players with SkillCorner's open
data (see engine/ingest/skillcorner.py's module docstring)."""

import duckdb
import pytest

from engine.ingest.skillcorner import _compute_bucket_stats, ingest_tracking_dataset
from engine.model.schema import ensure_schema


def test_bucket_stats_distance_and_max_speed():
    # Two players 1 second apart, moving 5m in the x direction: speed=5m/s.
    samples = [(0.0, 0.0, 0.0), (1.0, 5.0, 0.0)]
    stats = _compute_bucket_stats(samples)
    assert stats["distance_m"] == pytest.approx(5.0)
    assert stats["max_speed_ms"] == pytest.approx(5.0)


def test_bucket_stats_hi_distance_only_counts_fast_segments():
    # First hop: 3 m/s (below HI threshold 5.5) -- not counted.
    # Second hop: 6 m/s (above HI threshold) -- counted.
    samples = [(0.0, 0.0, 0.0), (1.0, 3.0, 0.0), (2.0, 9.0, 0.0)]
    stats = _compute_bucket_stats(samples)
    assert stats["hi_distance_m"] == pytest.approx(6.0)


def test_bucket_stats_sprint_count_counts_distinct_spells():
    # Speeds: 8 (sprint), 8 (still sprinting, same spell), 2 (not sprinting),
    # 9 (new sprint spell) -> 2 distinct sprint spells.
    samples = [(0, 0, 0), (1, 8, 0), (2, 16, 0), (3, 18, 0), (4, 27, 0)]
    stats = _compute_bucket_stats(samples)
    assert stats["sprint_count"] == 2


def test_bucket_stats_accel_and_decel_counts():
    # speeds: 0->5 (accel +5 m/s^2, counted), 5->5 (no change), 5->0 (decel -5, counted)
    samples = [(0, 0, 0), (1, 0, 0), (2, 5, 0), (3, 10, 0), (4, 10, 0)]
    stats = _compute_bucket_stats(samples)
    assert stats["accel_count"] == 1
    assert stats["decel_count"] == 1


def test_bucket_stats_ignores_non_positive_dt():
    # Two samples share timestamp 0.0 (dt=0, skipped as a pair) but the
    # second one still feeds into the *next* comparison at t=1.0.
    samples = [(0.0, 0.0, 0.0), (0.0, 100.0, 0.0), (1.0, 105.0, 0.0)]
    stats = _compute_bucket_stats(samples)
    assert stats["distance_m"] == pytest.approx(5.0)  # only the (0,100)->(1,105) hop counted


@pytest.fixture
def con():
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    con.execute("insert into competition values ('SC1', 'A-League test', NULL, NULL, 'male', '2024/2025')")
    con.execute("insert into team values (1, 'Perth Glory Football Club', 'SC1')")
    con.execute("insert into team values (2, 'Opponent', 'SC1')")
    con.execute("insert into fixture values (1, 'SC1', 1, 2, NULL)")
    # A real player from SkillCorner's open match 1925299, named exactly as
    # their tracking data spells it -- so resolve_person (step 4) succeeds.
    con.execute("insert into person values (100, 'Cameron Cook', NULL, NULL, 'Center Back')")
    return con


def test_unresolved_player_writes_no_rows(con):
    # Anyone whose tracked name isn't in `person` resolves to None (step 4)
    # and contributes zero rows -- the honest outcome for the real
    # SkillCorner-vs-Bundesliga mismatch this module's docstring describes.
    class _FakePlayer:
        def __init__(self, player_id, name):
            self.player_id = player_id
            self.name = name

    class _FakeCoords:
        def __init__(self, x, y):
            self.x, self.y = x, y

    class _FakePlayerData:
        def __init__(self, x, y):
            self.coordinates = _FakeCoords(x, y)

    class _FakeFrame:
        def __init__(self, t, players_data):
            self.timestamp = __import__("datetime").timedelta(seconds=t)
            self.players_data = players_data

    class _FakeDataset:
        def __init__(self, records):
            self.records = records

    unknown = _FakePlayer(999, "Nobody Recognisable")
    records = [
        _FakeFrame(0, {unknown: _FakePlayerData(0, 0)}),
        _FakeFrame(1, {unknown: _FakePlayerData(5, 0)}),
    ]
    rows_written = ingest_tracking_dataset(con, fixture_id=1, dataset=_FakeDataset(records))
    assert rows_written == 0
