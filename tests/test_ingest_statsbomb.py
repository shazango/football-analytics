"""Ingest test against the committed fixture slice (Union Berlin vs Bayer
Leverkusen, Bundesliga 2023/24, match 3895292 — see tests/fixtures/statsbomb).

Numbers below are hand-checked against that fixture, not just "did it run".
"""

import json
from pathlib import Path

import duckdb
import pytest

from engine.ingest.statsbomb import (
    _position_minutes,
    _set_primary_positions,
    ingest_competition,
)
from engine.metrics.foundation import qualifier_contains
from engine.model.schema import ensure_schema

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "statsbomb" / "data"
MATCH_ID = 3895292


@pytest.fixture(scope="module")
def con():
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    ingest_competition(con, competition_id=9, season_id=281, data_dir=FIXTURE_DIR)
    return con


def test_competition_row(con):
    rows = con.execute("select id, name, season, gender from competition").fetchall()
    assert rows == [("9-281", "1. Bundesliga", "2023/2024", "male")]


def test_teams_and_fixture(con):
    teams = {r[0] for r in con.execute("select name from team").fetchall()}
    assert teams == {"Union Berlin", "Bayer Leverkusen"}

    fixture = con.execute(
        "select id, competition_id, home_team_id, away_team_id from fixture"
    ).fetchall()
    assert fixture == [(MATCH_ID, "9-281", 190, 904)]


def test_event_count_and_types(con):
    total = con.execute("select count(*) from event").fetchone()[0]
    assert total == 3953  # full match event stream from the fixture

    shots = con.execute(
        "select count(*) from event where fixture_id = ? and type = 'SHOT'",
        [MATCH_ID],
    ).fetchone()[0]
    assert shots == 29  # matches the shot count in tests/fixtures/statsbomb


def test_on_target_shots_have_end_z(con):
    # Height in the goal frame — needed for psxg_ga (step 8). Only shots get
    # a 3D end coordinate from kloppy; everything else stays NULL.
    rows = con.execute(
        "select end_z from event where fixture_id = ? and type = 'SHOT' "
        "and outcome in ('SAVED', 'GOAL')",
        [MATCH_ID],
    ).fetchall()
    assert len(rows) > 0
    assert all(z is not None and z >= 0 for (z,) in rows)

    non_shot_z = con.execute(
        "select count(*) from event where fixture_id = ? and type != 'SHOT' and end_z is not null",
        [MATCH_ID],
    ).fetchone()[0]
    assert non_shot_z == 0


def test_shots_carry_freeze_frames(con):
    # The fixture keeps 360 frames for every shot (see how it was built).
    rows = con.execute(
        "select freeze_frame from event where fixture_id = ? and type = 'SHOT'",
        [MATCH_ID],
    ).fetchall()
    assert len(rows) == 29
    for (raw,) in rows:
        frame = json.loads(raw)
        assert frame  # non-empty list of {person_id, x, y, teammate, actor, keeper}
        assert any(p["keeper"] for p in frame), "every shot faces a keeper"


def test_shot_assist_passes_carry_xa(con):
    rows = con.execute(
        "select qualifiers from event where fixture_id = ? and type = 'PASS' "
        f"and ({qualifier_contains('Pass', 'SHOT_ASSIST', column='qualifiers')})",
        [MATCH_ID],
    ).fetchall()
    assert len(rows) == 22  # hand-checked against the fixture (see step 6)
    for (raw,) in rows:
        xa = json.loads(raw).get("xA")
        assert xa is not None and xa > 0


def test_appearance_minutes_within_match_length(con):
    rows = con.execute(
        "select minutes, start_min, end_min from appearance where fixture_id = ?",
        [MATCH_ID],
    ).fetchall()
    assert len(rows) > 0
    for minutes, start_min, end_min in rows:
        assert minutes == pytest.approx(end_min - start_min)
        assert 0 <= start_min <= end_min <= 110  # full match + stoppage time

    full_match_players = [r for r in rows if r[1] == 0.0]
    assert len(full_match_players) > 0


def test_events_reference_known_people_and_teams(con):
    orphan_people = con.execute(
        "select count(*) from event e left join person p on e.actor_person_id = p.id "
        "where e.actor_person_id is not null and p.id is null"
    ).fetchone()[0]
    assert orphan_people == 0

    orphan_teams = con.execute(
        "select count(*) from event e left join team t on e.team_id = t.id "
        "where e.team_id is not null and t.id is null"
    ).fetchone()[0]
    assert orphan_teams == 0


def test_coordinates_normalised_0_100(con):
    row = con.execute(
        "select min(location_x), max(location_x), min(location_y), max(location_y) "
        "from event where location_x is not null"
    ).fetchone()
    lo_x, hi_x, lo_y, hi_y = row
    assert 0 <= lo_x and hi_x <= 100
    assert 0 <= lo_y and hi_y <= 100


def test_completed_passes_have_end_coordinates(con):
    # Regression: PassEvent's end location is kloppy's `receiver_coordinates`,
    # not `end_coordinates`/`result_coordinates` — easy to miss since those
    # names cover carries/shots. A completed pass with no end point silently
    # breaks anything geometric (e.g. progressive-pass detection).
    row = con.execute(
        "select count(*), count(end_x) from event "
        "where fixture_id = ? and type = 'PASS' and outcome = 'COMPLETE'",
        [MATCH_ID],
    ).fetchone()
    total, with_end = row
    assert total > 0
    assert with_end == total


def test_possession_and_game_state(con):
    # The fixture's only goal: Bayer Leverkusen scores at ~52:15. State must
    # read "0" for both sides beforehand and flip to "1"/"-1" right after.
    rows = con.execute(
        "select sequence, team_id, possession_id, game_state, type, outcome "
        "from event where fixture_id = ? order by sequence",
        [MATCH_ID],
    ).fetchall()
    assert all(r[2] is not None for r in rows), "every event gets a possession_id"

    goal_idx = next(i for i, r in enumerate(rows) if r[4] == "SHOT" and r[5] == "GOAL")
    scoring_team = rows[goal_idx][1]
    assert rows[goal_idx][3] == "0"  # state just before the goal is level

    post_scoring = next(
        r for r in rows[goal_idx + 1 :] if r[1] == scoring_team
    )
    assert post_scoring[3] == "1"
    post_conceding = next(
        r for r in rows[goal_idx + 1 :] if r[1] is not None and r[1] != scoring_team
    )
    assert post_conceding[3] == "-1"


def test_ingest_is_idempotent(con):
    before = con.execute("select count(*) from event").fetchone()[0]
    ingest_competition(con, competition_id=9, season_id=281, data_dir=FIXTURE_DIR)
    after = con.execute("select count(*) from event").fetchone()[0]
    assert before == after


def test_primary_position_is_where_most_minutes_were_played(con):
    # Robin Gosens moves three times in this fixture: 45:00 at left wing
    # back, then two spells at left centre forward (2:30 + 13:21) and a
    # closing spell at centre attacking midfield. Taking the first listed
    # position happens to agree here; taking the *last* or the most
    # frequent would not. Only the minutes give left wing back.
    position = con.execute(
        "select primary_position from person where id = 6985"
    ).fetchone()[0]
    assert position == "Left Wing Back"

    # Lucas Tousart: Right Center Midfield 00:00-65:26, then Center
    # Defensive Midfield to the whistle. The longer spell wins.
    position = con.execute(
        "select primary_position from person where id = 3117"
    ).fetchone()[0]
    assert position == "Right Center Midfield"


def test_unused_sub_keeps_a_null_position(con):
    # A player named in the squad who never took the pitch has an empty
    # `positions` list, contributes no minutes, and must not be guessed at.
    position = con.execute(
        "select primary_position from person where id = 8239"
    ).fetchone()[0]
    assert position is None


def test_position_minutes_sums_split_spells():
    lineup = [
        {
            "lineup": [
                {
                    "player_id": 1,
                    "player_name": "Split Spell",
                    "positions": [
                        {"position": "Left Wing Back", "from": "00:00", "to": "45:00"},
                        {"position": "Center Forward", "from": "45:00", "to": "60:00"},
                        {"position": "Center Forward", "from": "70:00", "to": None},
                    ],
                }
            ]
        }
    ]
    assert _position_minutes(lineup, total_minutes=95.0) == [
        (1, "Left Wing Back", 45.0),
        (1, "Center Forward", 15.0),
        (1, "Center Forward", 25.0),
    ]

    # 45 at wing back vs 15 + 25 = 40 up front: the two forward spells only
    # beat it once they're summed, which is the point of accumulating
    # across stints (and across matches) rather than taking the longest one.
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    con.execute("INSERT INTO person VALUES (1, 'Split Spell', NULL, NULL, NULL)")
    _set_primary_positions(con, {1: {"Left Wing Back": 45.0, "Center Forward": 40.0}})
    assert con.execute(
        "select primary_position from person where id = 1"
    ).fetchone()[0] == "Left Wing Back"

    _set_primary_positions(con, {1: {"Left Wing Back": 45.0, "Center Forward": 50.0}})
    assert con.execute(
        "select primary_position from person where id = 1"
    ).fetchone()[0] == "Center Forward"
