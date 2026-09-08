"""Step 6: foundation-layer stats and their three adjustments.

Hand-computed expected values throughout (PHASE-0-BRIEF.md §10) against a
small synthetic warehouse — not the real season, so the arithmetic can be
traced by eye rather than trusted from a giant fixture.
"""

import json

import duckdb
import pytest

from engine.metrics import foundation, registry
from engine.metrics.definitions import MetricDefinition
from engine.model.schema import ensure_schema

COUNT_DEFN = MetricDefinition(
    id="_test", version=1, title="t", applies_to="all", min_sample=450,
    methodology="x", adjustments=["per_90", "possession", "opposition_strength"],
)
RATIO_DEFN = MetricDefinition(
    id="_test_ratio", version=1, title="t", applies_to="all", min_sample=20,
    methodology="x", adjustments=[],
)


@pytest.fixture
def con():
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    con.execute("insert into competition values ('C1', 'Comp', NULL, NULL, 'male', 'S1')")
    for tid, name in [(1, "A"), (2, "B"), (3, "C")]:
        con.execute("insert into team values (?, ?, 'C1')", [tid, name])
    return con


def _insert_event(con, fixture_id, seq, team_id, type_, outcome=None, loc=None, end=None,
                   qualifiers=None, actor=None):
    lx, ly = loc or (None, None)
    ex, ey = end or (None, None)
    con.execute(
        "insert into event values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            fixture_id, seq, seq * 1000, 1, type_, actor, team_id,
            lx, ly, ex, ey, None, outcome, None,
            json.dumps(qualifiers) if qualifiers else None, None, None,
        ],
    )


# --- adjustment arithmetic (per_90, possession, opposition_strength) -------

@pytest.fixture
def adjustment_con(con):
    # Player X (id=100, team A=1) plays two matches, each vs a different
    # opponent, with deliberately asymmetric shot counts/possession/xG so
    # per-fixture weighting bugs can't hide behind symmetric numbers.
    con.execute("insert into person values (100, 'X', NULL, NULL, 'Forward')")
    con.execute("insert into fixture values (11, 'C1', 1, 2, NULL)")  # A(home) vs B
    con.execute("insert into fixture values (12, 'C1', 3, 1, NULL)")  # C(home) vs A(away)
    con.execute("insert into appearance values (11, 100, 1, 90, 0, 90)")
    con.execute("insert into appearance values (12, 100, 1, 90, 0, 90)")

    seq = 0
    # F1 (fixture 11): X (team A) takes 1 shot; team B takes 2.
    _insert_event(con, 11, seq, 1, "SHOT", outcome="OFF_TARGET", qualifiers=dict(xG=0.2), actor=100)
    seq += 1
    _insert_event(con, 11, seq, 2, "SHOT", outcome="SAVED", qualifiers=dict(xG=0.3))
    seq += 1
    _insert_event(con, 11, seq, 2, "SHOT", outcome="OFF_TARGET", qualifiers=dict(xG=0.4))
    seq += 1
    # Filler events so team A has 6 total events, team B has 4, in fixture 11
    # (possession-share proxy = share of event count).
    for _ in range(5):
        _insert_event(con, 11, seq, 1, "PRESSURE")
        seq += 1
    for _ in range(2):
        _insert_event(con, 11, seq, 2, "PRESSURE")
        seq += 1

    # F2 (fixture 12): X (team A) takes 3 shots; team C takes 1.
    _insert_event(con, 12, seq, 1, "SHOT", outcome="OFF_TARGET", qualifiers=dict(xG=0.1), actor=100)
    seq += 1
    _insert_event(con, 12, seq, 1, "SHOT", outcome="SAVED", qualifiers=dict(xG=0.2), actor=100)
    seq += 1
    _insert_event(con, 12, seq, 1, "SHOT", outcome="POST", qualifiers=dict(xG=0.3), actor=100)
    seq += 1
    _insert_event(con, 12, seq, 3, "SHOT", outcome="SAVED", qualifiers=dict(xG=0.5))
    seq += 1
    # Filler: team A already has 3 events (the 3 shots); team C needs 8 more
    # (already has 1 shot) to reach A=3, C=9.
    for _ in range(8):
        _insert_event(con, 12, seq, 3, "PRESSURE")
        seq += 1
    return con


def test_raw_and_per90(adjustment_con):
    impl = registry.get_implementation("shots")
    raw = impl(adjustment_con, definition=COUNT_DEFN, person_id=100, competition_id="C1",
               season="S1", adjustment="raw")
    per90 = impl(adjustment_con, definition=COUNT_DEFN, person_id=100, competition_id="C1",
                 season="S1", adjustment="per_90")
    assert raw.value == 4  # 1 + 3
    assert raw.sample_size == 180
    assert per90.value == pytest.approx(2.0)  # 4 / (180/90)


def test_possession_adjustment(adjustment_con):
    # F1: team A share = 6/10 = 60% -> factor 50/60; F2: team A share = 3/12 = 25% -> factor 50/25
    expected_total = 1 * (50 / 60) + 3 * (50 / 25)
    expected_per90 = expected_total / 2.0
    impl = registry.get_implementation("shots")
    result = impl(adjustment_con, definition=COUNT_DEFN, person_id=100, competition_id="C1",
                  season="S1", adjustment="possession")
    assert result.value == pytest.approx(expected_per90)


def test_opposition_strength_adjustment(adjustment_con):
    # xGD per match: A vs B: (0.2 - 0.7) = -0.5; A vs C: (0.6 - 0.5) = +0.1
    # avg_xgd: A = (-0.5 + 0.1)/2 = -0.2; B = +0.5 (1 match); C = -0.1 (1 match)
    # ranked ascending: A(-0.2), C(-0.1), B(0.5) -> weights 0.7, 1.0, 1.3
    # opponent of F1 is B (weight 1.3); opponent of F2 is C (weight 1.0)
    expected_total = 1 * 1.3 + 3 * 1.0
    expected_per90 = expected_total / 2.0
    impl = registry.get_implementation("shots")
    result = impl(adjustment_con, definition=COUNT_DEFN, person_id=100, competition_id="C1",
                  season="S1", adjustment="opposition_strength")
    assert result.value == pytest.approx(expected_per90)


def test_unknown_adjustment_mode_raises(adjustment_con):
    impl = registry.get_implementation("shots")
    with pytest.raises(ValueError, match="unknown adjustment"):
        impl(adjustment_con, definition=COUNT_DEFN, person_id=100, competition_id="C1",
             season="S1", adjustment="nonsense")


def test_adjustment_not_declared_by_metric_raises(adjustment_con):
    bare = MetricDefinition(id="shots", version=1, title="t", applies_to="all",
                             min_sample=450, methodology="x", adjustments=["per_90"])
    impl = registry.get_implementation("shots")
    with pytest.raises(ValueError, match="does not declare support"):
        impl(adjustment_con, definition=bare, person_id=100, competition_id="C1",
             season="S1", adjustment="possession")


# --- stat filter correctness -----------------------------------------------

@pytest.fixture
def filter_con(con):
    con.execute("insert into person values (102, 'Z', NULL, NULL, 'Midfielder')")
    con.execute("insert into fixture values (31, 'C1', 1, 2, NULL)")
    con.execute("insert into appearance values (31, 102, 1, 90, 0, 90)")

    seq = 0
    events = [
        # progressive pass: clean qualifier via 25%-of-remaining-distance rule
        dict(type_="PASS", outcome="COMPLETE", loc=(40, 50), end=(90, 50)),
        # not progressive: too small a gain, doesn't enter the box
        dict(type_="PASS", outcome="COMPLETE", loc=(40, 50), end=(45, 50)),
        # would qualify geometrically, but incomplete -> excluded
        dict(type_="PASS", outcome="INCOMPLETE", loc=(40, 50), end=(95, 50)),
        # qualifies via box-entry only: progressed=3 < 25%*17=4.25, but end is in the box
        dict(type_="PASS", outcome="COMPLETE", loc=(83, 50), end=(86, 60)),
        # shot-assist pass: key pass + xA, deliberately not progressive
        dict(type_="PASS", outcome="COMPLETE", loc=(50, 50), end=(55, 50),
             qualifiers=dict(Pass="SHOT_ASSIST", xA=0.25)),
        # progressive carry
        dict(type_="CARRY", loc=(10, 50), end=(90, 50)),
        # not progressive carry
        dict(type_="CARRY", loc=(10, 50), end=(20, 50)),
        # duels
        dict(type_="DUEL", outcome="WON", qualifiers=dict(Duel="GROUND")),
        dict(type_="DUEL", outcome="WON", qualifiers=dict(Duel="TACKLE")),
        dict(type_="DUEL", outcome="LOST", qualifiers=dict(Duel="TACKLE")),
        dict(type_="DUEL", outcome="WON", qualifiers=dict(Duel="AERIAL")),
        dict(type_="DUEL", outcome="LOST", qualifiers=dict(Duel="AERIAL")),
        dict(type_="INTERCEPTION"),
        dict(type_="RECOVERY"),
    ]
    for e in events:
        _insert_event(
            con, 31, seq, 1, e["type_"], outcome=e.get("outcome"),
            loc=e.get("loc"), end=e.get("end"), qualifiers=e.get("qualifiers"), actor=102,
        )
        seq += 1
    return con


@pytest.mark.parametrize(
    "stat_id, expected_raw",
    [
        ("xa", 0.25),
        ("key_passes", 1),
        ("progressive_passes", 2),
        ("progressive_carries", 1),
        ("duels_won", 3),
        ("tackles", 2),
        ("aerials", 1),
        ("interceptions", 1),
        ("recoveries", 1),
    ],
)
def test_stat_filters(filter_con, stat_id, expected_raw):
    impl = registry.get_implementation(stat_id)
    result = impl(filter_con, definition=COUNT_DEFN, person_id=102, competition_id="C1",
                  season="S1", adjustment="raw")
    assert result.value == pytest.approx(expected_raw)


def test_shots_exclude_own_goals(con):
    con.execute("insert into person values (103, 'W', NULL, NULL, 'Defender')")
    con.execute("insert into fixture values (41, 'C1', 1, 2, NULL)")
    con.execute("insert into appearance values (41, 103, 1, 90, 0, 90)")
    _insert_event(con, 41, 0, 1, "SHOT", outcome="OFF_TARGET", actor=103)
    _insert_event(con, 41, 1, 1, "SHOT", outcome="OWN_GOAL", actor=103)

    impl = registry.get_implementation("shots")
    result = impl(con, definition=COUNT_DEFN, person_id=103, competition_id="C1",
                  season="S1", adjustment="raw")
    assert result.value == 1


# --- pass completion by third ----------------------------------------------

@pytest.fixture
def thirds_con(con):
    con.execute("insert into person values (101, 'Y', NULL, NULL, 'Midfielder')")
    con.execute("insert into fixture values (21, 'C1', 1, 2, NULL)")
    con.execute("insert into appearance values (21, 101, 1, 90, 0, 90)")

    passes = [
        (10, "COMPLETE"), (20, "COMPLETE"), (5, "INCOMPLETE"),  # defensive: 2/3
        (50, "COMPLETE"),  # middle: 1/1
        (70, "COMPLETE"), (90, "COMPLETE"), (95, "INCOMPLETE"),  # attacking: 2/3
    ]
    for seq, (x, outcome) in enumerate(passes):
        _insert_event(con, 21, seq, 1, "PASS", outcome=outcome, loc=(x, 50), actor=101)
    return con


@pytest.mark.parametrize(
    "third, expected_pct, expected_attempts",
    [
        ("defensive", 100 * 2 / 3, 3),
        ("middle", 100.0, 1),
        ("attacking", 100 * 2 / 3, 3),
    ],
)
def test_pass_completion_by_third(thirds_con, third, expected_pct, expected_attempts):
    impl = registry.get_implementation(f"pass_completion_{third}_third")
    result = impl(thirds_con, definition=RATIO_DEFN, person_id=101, competition_id="C1", season="S1")
    assert result.value == pytest.approx(expected_pct)
    assert result.sample_size == expected_attempts


def test_ratio_metric_rejects_adjustment(thirds_con):
    impl = registry.get_implementation("pass_completion_defensive_third")
    with pytest.raises(ValueError, match="ratio"):
        impl(thirds_con, definition=RATIO_DEFN, person_id=101, competition_id="C1",
             season="S1", adjustment="per_90")
