"""Step 9: throw_in_profile. Hand-computed expected values (PHASE-0-BRIEF.md
§10) against a small synthetic warehouse covering every branch of
fast/pressed/retained/aerial derivation."""

import json

import duckdb
import pytest

from engine.metrics import registry, throw_in  # noqa: F401 (registers impls)
from engine.metrics.definitions import MetricDefinition
from engine.model.schema import ensure_schema

DEFN = MetricDefinition(
    id="_test", version=1, title="t", applies_to="all", min_sample=1, methodology="x",
)


def _insert(con, seq, team, type_, ts, poss, loc=None, end=None, qualifiers=None,
            outcome=None, actor=None, freeze_frame=None):
    lx, ly = loc or (None, None)
    ex, ey = end or (None, None)
    con.execute(
        "insert into event values (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, NULL, ?)",
        [11, seq, ts, type_, actor, team, lx, ly, ex, ey, outcome, poss,
         json.dumps(qualifiers) if qualifiers else None,
         json.dumps(freeze_frame) if freeze_frame is not None else None],
    )


@pytest.fixture
def con():
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    con.execute("insert into competition values ('C1', 'Comp', NULL, NULL, 'male', 'S1')")
    con.execute("insert into team values (1, 'A', 'C1')")
    con.execute("insert into team values (2, 'B', 'C1')")
    con.execute("insert into person values (100, 'Thrower', NULL, NULL, 'Right Back')")
    con.execute("insert into person values (101, 'Receiver', NULL, NULL, 'Center Forward')")
    con.execute("insert into person values (200, 'Defender', NULL, NULL, 'Center Back')")
    con.execute("insert into fixture values (11, 'C1', 1, 2, NULL)")
    con.execute("insert into appearance values (11, 100, 1, 90, 0, 90)")
    con.execute("insert into appearance values (11, 200, 2, 90, 0, 90)")

    throw_qualifiers = {"SetPiece": "THROW_IN"}

    # Throw 1: fast, pressed, retained (chain runs long enough).
    _insert(con, 9, 2, "BALL_OUT", 0, 99)
    _insert(con, 10, 1, "PASS", 5000, 100, loc=(50, 50), end=(60, 55),
            qualifiers=throw_qualifiers, outcome="COMPLETE", actor=100)
    _insert(con, 11, 2, "PRESSURE", 8000, 100)
    _insert(con, 12, 1, "PASS", 12000, 100, outcome="COMPLETE")

    # Throw 2: not fast, not pressed, not retained (dies immediately).
    _insert(con, 19, 2, "BALL_OUT", 10000, 109)
    _insert(con, 20, 1, "PASS", 25000, 110, loc=(50, 50), end=(55, 50),
            qualifiers=throw_qualifiers, outcome="COMPLETE", actor=100)

    # Throw 3: fast, pressed, retained via ending in a shot (short duration).
    _insert(con, 29, 2, "BALL_OUT", 30000, 119)
    _insert(con, 30, 1, "PASS", 31000, 120, loc=(50, 50), end=(45, 50),
            qualifiers=throw_qualifiers, outcome="COMPLETE", actor=100)
    _insert(con, 31, 1, "SHOT", 31500, 120, outcome="OFF_TARGET")
    _insert(con, 32, 2, "PRESSURE", 32000, 120)

    # Throw 4: fast (exactly at the 8s boundary), aerial duel won by thrower's team.
    _insert(con, 39, 2, "BALL_OUT", 40000, 129)
    _insert(con, 40, 1, "PASS", 48000, 130, loc=(80, 50), end=(85, 50),
            qualifiers=throw_qualifiers, outcome="COMPLETE", actor=100)
    _insert(con, 41, 1, "DUEL", 49000, 130, outcome="WON",
            qualifiers={"Duel": "AERIAL"})

    # Throw 5: not fast, aerial duel lost (opponent wins it).
    _insert(con, 49, 2, "BALL_OUT", 60000, 139)
    _insert(con, 50, 1, "PASS", 70000, 140, loc=(50, 50), end=(52, 50),
            qualifiers=throw_qualifiers, outcome="COMPLETE", actor=100)
    _insert(con, 51, 2, "DUEL", 71000, 140, outcome="WON",
            qualifiers={"Duel": "AERIAL"})

    # Throw 6: "clever" via the throw itself bypassing an opponent (at x=60,
    # in front before the throw at x=50, behind it after at x=70).
    _insert(con, 59, 2, "BALL_OUT", 80000, 149)
    _insert(con, 60, 1, "PASS", 90000, 150, loc=(50, 50), end=(70, 50),
            qualifiers=throw_qualifiers, outcome="COMPLETE", actor=100,
            freeze_frame=[{"x": 60, "y": 50, "teammate": False, "actor": False, "keeper": False}])

    # Throw 7: the throw itself doesn't break a line (opponent at x=90 stays
    # in front, 90 > 55), but the first receiver's next touch does (same
    # opponent at x=90, now bypassed: 90 > 55 before, 90 <= 95 after).
    _insert(con, 69, 2, "BALL_OUT", 100000, 159)
    _insert(con, 70, 1, "PASS", 110000, 160, loc=(50, 50), end=(55, 50),
            qualifiers=throw_qualifiers, outcome="COMPLETE", actor=100,
            freeze_frame=[{"x": 90, "y": 50, "teammate": False, "actor": False, "keeper": False}])
    _insert(con, 71, 1, "PASS", 111000, 160, loc=(55, 50), end=(95, 50),
            outcome="COMPLETE", actor=101,
            freeze_frame=[{"x": 90, "y": 50, "teammate": False, "actor": False, "keeper": False}])

    return con


def test_derive_throw_fast_pressed_retained_flags(con):
    throws = throw_in._throws_taken(con, 100, "C1")
    assert len(throws) == 7
    flags = [(t["fast"], t["pressed"], t["retained"]) for t in throws]
    assert flags == [
        (True, True, True),  # throw 1
        (False, False, False),  # throw 2
        (True, True, True),  # throw 3: retained via shot despite short duration
        (True, False, False),  # throw 4: fast at exactly 8000ms
        (False, False, False),  # throw 5
        (False, False, False),  # throw 6
        (False, False, False),  # throw 7
    ]


def test_derive_throw_clever_flag(con):
    throws = throw_in._throws_taken(con, 100, "C1")
    clever_flags = [t["clever"] for t in throws]
    assert clever_flags == [False, False, False, False, False, True, True]


def test_clever_share_metric(con):
    result = registry.get_implementation("throw_in_clever_share")(
        con, DEFN, person_id=100, competition_id="C1", season="S1"
    )
    # 2 of 7 throws are "clever" (throws 6 and 7).
    assert result.value == pytest.approx(100 * 2 / 7)
    assert result.sample_size == 7


def test_derive_throw_aerial_fields(con):
    throws = throw_in._throws_taken(con, 100, "C1")
    assert [t["has_aerial"] for t in throws] == [False, False, False, True, True, False, False]
    assert [t["aerial_won"] for t in throws] == [False, False, False, True, False, False, False]


def test_derive_throw_distance_and_territory(con):
    throws = throw_in._throws_taken(con, 100, "C1")
    distances = [round(t["distance"], 4) for t in throws]
    territories = [t["territory_gained"] for t in throws]
    assert distances == [11.1803, 5.0, 5.0, 5.0, 2.0, 20.0, 5.0]
    assert territories == [10, 5, -5, 5, 2, 20, 5]


def test_retention_under_pressure(con):
    result = registry.get_implementation("throw_in_retention_under_pressure")(
        con, DEFN, person_id=100, competition_id="C1", season="S1"
    )
    # Pressured: throws 1 and 3, both retained -> 2/2 = 100%.
    assert result.value == pytest.approx(100.0)
    assert result.sample_size == 2


def test_retention_rate(con):
    result = registry.get_implementation("throw_in_retention_rate")(
        con, DEFN, person_id=100, competition_id="C1", season="S1"
    )
    # Retained: throws 1 and 3 out of 7 -> 28.57%.
    assert result.value == pytest.approx(100 * 2 / 7)
    assert result.sample_size == 7


def test_distance_metric(con):
    result = registry.get_implementation("throw_in_distance")(
        con, DEFN, person_id=100, competition_id="C1", season="S1"
    )
    assert result.value == pytest.approx((11.1803399 + 5 + 5 + 5 + 2 + 20 + 5) / 7)
    assert result.sample_size == 7


def test_territory_gained_metric(con):
    result = registry.get_implementation("throw_in_territory_gained")(
        con, DEFN, person_id=100, competition_id="C1", season="S1"
    )
    assert result.value == pytest.approx(42 / 7)
    assert result.sample_size == 7


def test_aerial_win_rate_metric(con):
    result = registry.get_implementation("throw_in_aerial_win_rate")(
        con, DEFN, person_id=100, competition_id="C1", season="S1"
    )
    # Contested: throws 4 (won) and 5 (lost) -> 1/2 = 50%.
    assert result.value == pytest.approx(50.0)
    assert result.sample_size == 2


def test_retention_allowed_defensive_mirror(con):
    # From team B's (person 200's) perspective, watching team A's throws.
    result = registry.get_implementation("throw_in_retention_allowed")(
        con, DEFN, person_id=200, competition_id="C1", season="S1"
    )
    assert result.value == pytest.approx(100 * 2 / 7)  # same 2/7 as retention_rate
    assert result.sample_size == 7


def test_no_throws_returns_none(con):
    con.execute("insert into person values (300, 'Nobody', NULL, NULL, 'Left Wing')")
    result = registry.get_implementation("throw_in_retention_rate")(
        con, DEFN, person_id=300, competition_id="C1", season="S1"
    )
    assert result.value is None
    assert result.sample_size == 0
