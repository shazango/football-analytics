"""throw_in_profile (PHASE-0-BRIEF.md §7.3, build order step 9).

Throw-ins are StatsBomb PASS events with `qualifiers.SetPiece = 'THROW_IN'`
— not their own event type. Every threshold below is an explicit,
documented operational choice (empirically checked against this
warehouse — see docs/metrics/throw_in_profile.md), same spirit as
progressive-pass (step 6): the brief gives the shape, not exact numbers.

**"Clever"** (does the throw or first receiver break a defensive line)
reuses line_break_value's bypass detection (step 11, added once that
existed) — see `_breaks_line`.
"""

import json
import math

from engine.metrics import registry
from engine.metrics.line_break import _bypassed_value_and_count
from engine.metrics.runtime import MetricResult

FAST_THROW_MS = 8000  # ball-out to throw-taken, "quickly" taken
PRESSED_WINDOW_MS = 8000  # opposing PRESSURE event within this long after the throw counts as "pressed"
RETAINED_MIN_DURATION_MS = 5000  # throw's own possession chain lasts >= this...
# ...or ends in a shot by the throwing team, whichever comes first: "retained".


def _row_breaks_line(row: tuple | None) -> bool:
    if row is None:
        return False
    location_x, end_x, freeze_frame_json = row
    if end_x is None or not freeze_frame_json:
        return False
    freeze_frame = json.loads(freeze_frame_json)
    if not freeze_frame:
        return False
    _, count = _bypassed_value_and_count(location_x, end_x, freeze_frame)
    return count > 0


def _breaks_line(con, fixture_id: int, sequence: int, team_id: int, possession_id: int) -> bool:
    """"Clever": does the throw itself, or the first receiver's next touch
    in the same chain, bypass at least one opponent (line_break_value's
    detection, step 11)?"""
    throw_row = con.execute(
        "select location_x, end_x, freeze_frame from event where fixture_id = ? and sequence = ?",
        [fixture_id, sequence],
    ).fetchone()
    if _row_breaks_line(throw_row):
        return True

    next_row = con.execute(
        "select location_x, end_x, freeze_frame from event where fixture_id = ? "
        "and possession_id = ? and sequence > ? and team_id = ? and type in ('PASS', 'CARRY') "
        "order by sequence asc limit 1",
        [fixture_id, possession_id, sequence, team_id],
    ).fetchone()
    return _row_breaks_line(next_row)


def _derive_throw(con, row: tuple) -> dict:
    fixture_id, sequence, team_id, x, y, end_x, end_y, possession_id, ts = row

    ball_out = con.execute(
        "select timestamp_ms from event where fixture_id = ? and sequence < ? "
        "and type = 'BALL_OUT' order by sequence desc limit 1",
        [fixture_id, sequence],
    ).fetchone()
    fast = ball_out is not None and (ts - ball_out[0]) <= FAST_THROW_MS

    pressed = (
        con.execute(
            "select count(*) from event where fixture_id = ? and possession_id = ? "
            "and type = 'PRESSURE' and team_id != ? and timestamp_ms between ? and ?",
            [fixture_id, possession_id, team_id, ts, ts + PRESSED_WINDOW_MS],
        ).fetchone()[0]
        > 0
    )

    last_ts, has_shot = con.execute(
        "select max(timestamp_ms), max(case when type = 'SHOT' and team_id = ? then 1 else 0 end) "
        "from event where fixture_id = ? and possession_id = ?",
        [team_id, fixture_id, possession_id],
    ).fetchone()
    retained = (last_ts - ts) >= RETAINED_MIN_DURATION_MS or bool(has_shot)

    aerials = con.execute(
        "select team_id, outcome from event where fixture_id = ? and possession_id = ? "
        "and type = 'DUEL' and json_extract_string(qualifiers, '$.Duel') = 'AERIAL'",
        [fixture_id, possession_id],
    ).fetchall()
    has_aerial = len(aerials) > 0
    aerial_won = any(t == team_id and o == "WON" for t, o in aerials)

    distance = math.hypot(end_x - x, end_y - y) if end_x is not None else None
    territory_gained = (end_x - x) if end_x is not None else None
    clever = _breaks_line(con, fixture_id, sequence, team_id, possession_id)

    return {
        "fast": fast,
        "pressed": pressed,
        "retained": retained,
        "distance": distance,
        "territory_gained": territory_gained,
        "has_aerial": has_aerial,
        "aerial_won": aerial_won,
        "clever": clever,
    }


def _throws_taken(con, person_id: int, competition_id: str) -> list[dict]:
    """Every throw-in taken by this person, with derived per-throw fields."""
    rows = con.execute(
        "select t.fixture_id, t.sequence, t.team_id, t.location_x, t.location_y, "
        "t.end_x, t.end_y, t.possession_id, t.timestamp_ms "
        "from event t join fixture f on f.id = t.fixture_id "
        "where t.actor_person_id = ? and f.competition_id = ? and t.type = 'PASS' "
        "and json_extract_string(t.qualifiers, '$.SetPiece') = 'THROW_IN'",
        [person_id, competition_id],
    ).fetchall()
    return [_derive_throw(con, r) for r in rows]


def _opposing_throws(con, person_id: int, competition_id: str) -> list[dict]:
    """Throw-ins taken by the opposing team, across every fixture this
    person appeared in — the defensive mirror of _throws_taken. Same
    "ignore substitution timing" simplification as psxg_ga (step 8)."""
    fixture_teams = con.execute(
        "select fixture_id, team_id from appearance where person_id = ? "
        "and fixture_id in (select id from fixture where competition_id = ?)",
        [person_id, competition_id],
    ).fetchall()
    rows = []
    for fixture_id, own_team_id in fixture_teams:
        rows.extend(
            con.execute(
                "select fixture_id, sequence, team_id, location_x, location_y, end_x, end_y, "
                "possession_id, timestamp_ms from event where fixture_id = ? and type = 'PASS' "
                "and json_extract_string(qualifiers, '$.SetPiece') = 'THROW_IN' and team_id != ?",
                [fixture_id, own_team_id],
            ).fetchall()
        )
    return [_derive_throw(con, r) for r in rows]


def _make_thrower_impl(kind: str):
    def impl(con, definition, person_id, competition_id, season, fixture_id=None, **_):
        throws = _throws_taken(con, person_id, competition_id)

        if kind == "retention_under_pressure":
            population = [t for t in throws if t["pressed"]]
            n = len(population)
            value = 100.0 * sum(t["retained"] for t in population) / n if n else None
        elif kind == "retention_rate":
            n = len(throws)
            value = 100.0 * sum(t["retained"] for t in throws) / n if n else None
        elif kind == "distance":
            values = [t["distance"] for t in throws if t["distance"] is not None]
            n = len(values)
            value = sum(values) / n if n else None
        elif kind == "territory_gained":
            values = [t["territory_gained"] for t in throws if t["territory_gained"] is not None]
            n = len(values)
            value = sum(values) / n if n else None
        elif kind == "aerial_win_rate":
            population = [t for t in throws if t["has_aerial"]]
            n = len(population)
            value = 100.0 * sum(t["aerial_won"] for t in population) / n if n else None
        else:  # clever_share
            n = len(throws)
            value = 100.0 * sum(t["clever"] for t in throws) / n if n else None

        return MetricResult(value=value, sample_size=n)

    return impl


def _retention_allowed_impl(con, definition, person_id, competition_id, season, fixture_id=None, **_):
    throws = _opposing_throws(con, person_id, competition_id)
    n = len(throws)
    value = 100.0 * sum(t["retained"] for t in throws) / n if n else None
    return MetricResult(value=value, sample_size=n)


registry.register("throw_in_retention_under_pressure")(_make_thrower_impl("retention_under_pressure"))
registry.register("throw_in_retention_rate")(_make_thrower_impl("retention_rate"))
registry.register("throw_in_distance")(_make_thrower_impl("distance"))
registry.register("throw_in_territory_gained")(_make_thrower_impl("territory_gained"))
registry.register("throw_in_aerial_win_rate")(_make_thrower_impl("aerial_win_rate"))
registry.register("throw_in_clever_share")(_make_thrower_impl("clever_share"))
registry.register("throw_in_retention_allowed")(_retention_allowed_impl)
