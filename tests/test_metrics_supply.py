"""Step 10: supply_attribution. Hand-computed expected values (PHASE-0-
BRIEF.md §10) against a small synthetic warehouse covering every branch of
supplier detection (direct assist, skipped intervening touch, opponent
pressure vs. genuine contest, no preceding event, own goal / no-xG
exclusion)."""

import json

import duckdb
import pytest

from engine.metrics import registry, supply  # noqa: F401 (registers impls)
from engine.metrics.definitions import MetricDefinition
from engine.model.schema import ensure_schema

DEFN = MetricDefinition(
    id="_test", version=1, title="t", applies_to="all", min_sample=1, methodology="x",
)


def _insert(con, seq, team, type_, actor, poss, outcome=None, xg=None):
    qualifiers = {"xG": xg} if xg is not None else None
    con.execute(
        "insert into event values (?, ?, ?, 1, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, ?, ?, ?, NULL, NULL)",
        [11, seq, seq * 1000, type_, actor, team, outcome, poss,
         json.dumps(qualifiers) if qualifiers else None],
    )


@pytest.fixture
def con():
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    con.execute("insert into competition values ('C1', 'Comp', NULL, NULL, 'male', 'S1')")
    con.execute("insert into team values (1, 'A', 'C1')")
    con.execute("insert into team values (2, 'B', 'C1')")
    con.execute("insert into person values (100, 'Shooter', NULL, NULL, 'Center Forward')")
    con.execute("insert into person values (101, 'Supplier1', NULL, NULL, 'Left Wing')")
    con.execute("insert into person values (102, 'Supplier2', NULL, NULL, 'Right Wing')")
    con.execute("insert into person values (200, 'Defender', NULL, NULL, 'Center Back')")
    con.execute("insert into fixture values (11, 'C1', 1, 2, NULL)")

    # Shot A (poss 100): teammate pass, then shooter's own carry, then shot.
    # Supplier must skip the shooter's own intervening touch.
    _insert(con, 1, 1, "PASS", 101, 100)
    _insert(con, 2, 1, "CARRY", 100, 100)
    _insert(con, 3, 1, "SHOT", 100, 100, outcome="SAVED", xg=0.3)

    # Shot B (poss 101): direct assist, no intervening touch.
    _insert(con, 4, 1, "PASS", 102, 101)
    _insert(con, 5, 1, "SHOT", 100, 101, outcome="SAVED", xg=0.2)

    # Shot C (poss 102): teammate pass, THEN an opponent DUEL (genuine
    # contest) -> walk stops there, shot counts as unassisted despite the
    # earlier pass.
    _insert(con, 6, 1, "PASS", 101, 102)
    _insert(con, 7, 2, "DUEL", 200, 102, outcome="LOST")
    _insert(con, 8, 1, "SHOT", 100, 102, outcome="SAVED", xg=0.4)

    # Shot D (poss 103): teammate pass, then opponent PRESSURE (not a
    # contest) -> walk skips past it and still finds the supplier.
    _insert(con, 9, 1, "PASS", 101, 103)
    _insert(con, 10, 2, "PRESSURE", 200, 103)
    _insert(con, 11, 1, "SHOT", 100, 103, outcome="SAVED", xg=0.1)

    # Shot E (poss 104): no preceding event at all -> unassisted.
    _insert(con, 12, 1, "SHOT", 100, 104, outcome="SAVED", xg=0.15)

    # Shot F (poss 105): own goal -> excluded entirely (no xG assigned, and
    # would be a nonsensical "shot taken" even if it had one).
    _insert(con, 13, 1, "SHOT", 100, 105, outcome="OWN_GOAL")

    # Shot G (poss 106): on target but StatsBomb assigned no xG -> excluded.
    _insert(con, 14, 1, "SHOT", 100, 106, outcome="SAVED")

    return con


def test_supplier_skips_shooters_own_touch(con):
    breakdown = supply.supply_breakdown(con, 100, "C1")
    # Shot A's supplier is 101 (the pass), not None from the carry.
    assert breakdown[101] == pytest.approx(0.3 + 0.1)  # shots A and D


def test_supplier_direct_assist(con):
    shots = supply._shots_with_xg(con, 100, "C1")
    shot_b = next(xg_supplier for xg_supplier in shots if xg_supplier[0] == pytest.approx(0.2))
    assert shot_b[1] == 102


def test_supplier_stops_at_genuine_opponent_contest(con):
    shots = supply._shots_with_xg(con, 100, "C1")
    shot_c = next(s for s in shots if s[0] == pytest.approx(0.4))
    assert shot_c[1] is None  # unassisted, despite the earlier pass


def test_supplier_skips_opponent_pressure(con):
    shots = supply._shots_with_xg(con, 100, "C1")
    shot_d = next(s for s in shots if s[0] == pytest.approx(0.1))
    assert shot_d[1] == 101


def test_no_preceding_event_is_unassisted(con):
    shots = supply._shots_with_xg(con, 100, "C1")
    shot_e = next(s for s in shots if s[0] == pytest.approx(0.15))
    assert shot_e[1] is None


def test_own_goal_and_missing_xg_excluded(con):
    shots = supply._shots_with_xg(con, 100, "C1")
    assert len(shots) == 5  # A, B, C, D, E only -- F (own goal) and G (no xG) excluded


def test_supply_breakdown_full(con):
    breakdown = supply.supply_breakdown(con, 100, "C1")
    assert breakdown == {101: pytest.approx(0.4), 102: pytest.approx(0.2), None: pytest.approx(0.55)}


def test_assisted_xg_share(con):
    result = registry.get_implementation("supply_assisted_xg_share")(
        con, DEFN, person_id=100, competition_id="C1", season="S1"
    )
    assert result.value == pytest.approx(100 * 0.6 / 1.15)
    assert result.sample_size == 5


def test_top_supplier_share(con):
    result = registry.get_implementation("supply_top_supplier_share")(
        con, DEFN, person_id=100, competition_id="C1", season="S1"
    )
    assert result.value == pytest.approx(100 * 0.4 / 0.6)
    assert result.sample_size == 3


def test_herfindahl_index(con):
    result = registry.get_implementation("supply_herfindahl_index")(
        con, DEFN, person_id=100, competition_id="C1", season="S1"
    )
    expected = (0.4 / 0.6) ** 2 + (0.2 / 0.6) ** 2
    assert result.value == pytest.approx(expected)
    assert result.sample_size == 3


def test_no_shots_returns_none(con):
    con.execute("insert into person values (300, 'Nobody', NULL, NULL, 'Left Back')")
    result = registry.get_implementation("supply_assisted_xg_share")(
        con, DEFN, person_id=300, competition_id="C1", season="S1"
    )
    assert result.value is None
    assert result.sample_size == 0
