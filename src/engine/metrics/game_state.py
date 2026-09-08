"""game_state_response (PHASE-0-BRIEF.md §7.6, build order step 12).

Splits foundation metrics by match state — leading, level, trailing by
margin — and by two headline time-scoped cuts named in the brief: output
in the 10 minutes after conceding, and pressing intensity when 2+ goals
down. See docs/metrics/game_state_response.md for the full scope
decision (a curated 3-stat subset, not all 14 foundation metrics) and
why several buckets are thin-to-empty for this particular demo team.

**Naming discipline (brief §7.6, verbatim):** this is a game-state
RESPONSE profile. It is never labelled as a psychological attribute of an
individual. The word "morale" must never appear in this module, its
tests, or its docs — and doesn't, anywhere in this codebase.

Mechanism: `event.game_state` (derived at ingest, step 3) already gives
the score margin for the acting team as of just before that event —
reused directly via SQL to classify individual events into a margin
bucket. What's new here is the *denominator*: minutes played within a
bucket, which needs a reconstructed team score-state timeline (goal
timestamps aren't stored per-minute anywhere) intersected against each
appearance window.

Re-registers "shots"/"duels_won"/"tackles" (STATE_SCOPED_STATS) with a
wrapper that delegates to foundation.py's original implementation when no
`game_state_bucket` is requested, and only diverges when one is — see
`_make_state_scoped_impl`. This only takes effect if this module is
imported; foundation.py itself is untouched.
"""

from engine.metrics import foundation, registry
from engine.metrics.runtime import MetricResult

MARGIN_BUCKETS = ("leading", "level", "trailing_1", "trailing_2plus")
AFTER_CONCEDING_BUCKET = "after_conceding_10min"
STATE_SCOPED_STATS = ("shots", "duels_won", "tackles")

AFTER_CONCEDING_WINDOW_MS = 10 * 60 * 1000

_MARGIN_BUCKET_SQL = {
    "leading": "try_cast(e.game_state as integer) > 0",
    "level": "try_cast(e.game_state as integer) = 0",
    "trailing_1": "try_cast(e.game_state as integer) = -1",
    "trailing_2plus": "try_cast(e.game_state as integer) <= -2",
}


def classify_margin(game_state: str | None) -> str | None:
    if game_state is None:
        return None
    margin = int(game_state)
    if margin > 0:
        return "leading"
    if margin == 0:
        return "level"
    if margin == -1:
        return "trailing_1"
    return "trailing_2plus"


def _goal_events(con, fixture_id: int) -> list[tuple[int, int]]:
    """[(timestamp_ms, scoring_team_id)] for every goal in a fixture,
    ordered by time. Own goals credit the *other* team — same convention
    as `_possession_and_state` in engine/ingest/statsbomb.py (step 3)."""
    rows = con.execute(
        "select timestamp_ms, team_id, outcome from event "
        "where fixture_id = ? and type = 'SHOT' and outcome in ('GOAL', 'OWN_GOAL') "
        "order by timestamp_ms",
        [fixture_id],
    ).fetchall()
    home_id, away_id = con.execute(
        "select home_team_id, away_team_id from fixture where id = ?", [fixture_id]
    ).fetchone()
    goals = []
    for ts, team_id, outcome in rows:
        scoring_team = team_id if outcome == "GOAL" else (away_id if team_id == home_id else home_id)
        goals.append((ts, scoring_team))
    return goals


def _state_breakpoints(con, fixture_id: int, team_id: int) -> list[tuple[int, int]]:
    """[(timestamp_ms, state_from_this_point)] for `team_id`'s own score
    margin across a fixture, starting (0, 0) at kickoff."""
    state = 0
    breakpoints = [(0, 0)]
    for ts, scoring_team in _goal_events(con, fixture_id):
        state += 1 if scoring_team == team_id else -1
        breakpoints.append((ts, state))
    return breakpoints


def _bucket_at(breakpoints: list[tuple[int, int]], ts: float) -> str:
    state = 0
    for bp_ts, bp_state in breakpoints:
        if bp_ts <= ts:
            state = bp_state
        else:
            break
    return classify_margin(str(state))


def _minutes_by_bucket_in_fixture(con, fixture_id: int, team_id: int,
                                   start_min: float, end_min: float) -> dict[str, float]:
    breakpoints = _state_breakpoints(con, fixture_id, team_id)
    start_ms, end_ms = start_min * 60000, end_min * 60000
    boundaries = sorted({start_ms, end_ms} | {ts for ts, _ in breakpoints if start_ms < ts < end_ms})
    out: dict[str, float] = {}
    for a, b in zip(boundaries, boundaries[1:]):
        bucket = _bucket_at(breakpoints, (a + b) / 2)
        out[bucket] = out.get(bucket, 0.0) + (b - a) / 60000.0
    return out


def minutes_by_margin_bucket(con, person_id: int, competition_id: str) -> dict[str, float]:
    """Total minutes this person played in each margin bucket, across
    every fixture in this competition-season."""
    rows = con.execute(
        "select a.fixture_id, a.team_id, a.start_min, a.end_min from appearance a "
        "join fixture f on f.id = a.fixture_id where a.person_id = ? and f.competition_id = ?",
        [person_id, competition_id],
    ).fetchall()
    total: dict[str, float] = {}
    for fixture_id, team_id, start_min, end_min in rows:
        for bucket, minutes in _minutes_by_bucket_in_fixture(con, fixture_id, team_id, start_min, end_min).items():
            total[bucket] = total.get(bucket, 0.0) + minutes
    return total


def _after_conceding_windows(con, fixture_id: int, team_id: int) -> list[tuple[int, int]]:
    return [
        (ts, ts + AFTER_CONCEDING_WINDOW_MS)
        for ts, scoring_team in _goal_events(con, fixture_id)
        if scoring_team != team_id
    ]


def _minutes_after_conceding_in_fixture(con, fixture_id: int, team_id: int,
                                         start_min: float, end_min: float) -> float:
    # ponytail: overlapping windows (two goals conceded within 10 minutes
    # of each other) double-count that overlap. Rare enough not to bother
    # merging intervals for Phase 0 — see methodology doc.
    start_ms, end_ms = start_min * 60000, end_min * 60000
    total_ms = 0
    for w_start, w_end in _after_conceding_windows(con, fixture_id, team_id):
        total_ms += max(0, min(end_ms, w_end) - max(start_ms, w_start))
    return total_ms / 60000.0


def _raw_value_by_margin(con, spec, person_id: int, competition_id: str, bucket: str) -> float:
    row = con.execute(
        f"select sum({spec.value_expr}) from event e "
        "join appearance a on a.fixture_id = e.fixture_id and a.person_id = e.actor_person_id "
        "join fixture f on f.id = e.fixture_id "
        f"where e.actor_person_id = ? and f.competition_id = ? and ({spec.event_where}) "
        f"and ({_MARGIN_BUCKET_SQL[bucket]})",
        [person_id, competition_id],
    ).fetchone()
    return row[0] or 0.0


def _raw_after_conceding(con, spec, person_id: int, competition_id: str) -> tuple[float, float]:
    fixture_teams = con.execute(
        "select a.fixture_id, a.team_id, a.start_min, a.end_min from appearance a "
        "join fixture f on f.id = a.fixture_id where a.person_id = ? and f.competition_id = ?",
        [person_id, competition_id],
    ).fetchall()
    total_value = 0.0
    total_minutes = 0.0
    for fixture_id, team_id, start_min, end_min in fixture_teams:
        windows = _after_conceding_windows(con, fixture_id, team_id)
        if not windows:
            continue
        total_minutes += _minutes_after_conceding_in_fixture(con, fixture_id, team_id, start_min, end_min)
        for w_start, w_end in windows:
            row = con.execute(
                f"select sum({spec.value_expr}) from event e "
                f"where e.actor_person_id = ? and e.fixture_id = ? and ({spec.event_where}) "
                "and e.timestamp_ms between ? and ?",
                [person_id, fixture_id, w_start, w_end],
            ).fetchone()
            total_value += row[0] or 0.0
    return total_value, total_minutes


def _make_state_scoped_impl(stat_id: str):
    base_impl = foundation._make_count_impl(stat_id)
    spec = foundation.STAT_SPECS[stat_id]

    def impl(con, definition, person_id, competition_id, season, fixture_id=None,
              adjustment="per_90", game_state_bucket=None, **_):
        if game_state_bucket is None:
            return base_impl(con, definition=definition, person_id=person_id,
                              competition_id=competition_id, season=season,
                              fixture_id=fixture_id, adjustment=adjustment)

        if game_state_bucket not in definition.game_state_buckets:
            raise ValueError(
                f"metric '{definition.id}' does not declare support for "
                f"game_state_bucket '{game_state_bucket}' (declares {definition.game_state_buckets})"
            )
        if adjustment not in ("raw", "per_90"):
            raise ValueError(f"unknown adjustment mode '{adjustment}'")

        if game_state_bucket == AFTER_CONCEDING_BUCKET:
            total_value, total_minutes = _raw_after_conceding(con, spec, person_id, competition_id)
        else:
            total_value = _raw_value_by_margin(con, spec, person_id, competition_id, game_state_bucket)
            total_minutes = minutes_by_margin_bucket(con, person_id, competition_id).get(game_state_bucket, 0.0)

        if adjustment == "raw":
            value = total_value
        else:
            value = (total_value / (total_minutes / 90)) if total_minutes else None
        return MetricResult(value=value, sample_size=int(round(total_minutes)))

    return impl


for _stat_id in STATE_SCOPED_STATS:
    registry.register(_stat_id)(_make_state_scoped_impl(_stat_id))


# --- pressing intensity when 2+ down (headline cut, brief §7.6) ------------

def _trailing_2plus_windows(con, fixture_id: int, team_id: int) -> list[tuple[int, int]]:
    """[(start_ms, end_ms)] sub-intervals of the match where `team_id`'s
    own margin is <= -2, from the same breakpoints minutes-by-bucket uses."""
    breakpoints = _state_breakpoints(con, fixture_id, team_id)
    match_end_ms = con.execute(
        "select max(timestamp_ms) from event where fixture_id = ?", [fixture_id]
    ).fetchone()[0]
    windows = []
    for i, (ts, state) in enumerate(breakpoints):
        if state <= -2:
            end = breakpoints[i + 1][0] if i + 1 < len(breakpoints) else match_end_ms
            windows.append((ts, end))
    return windows


def _pressing_intensity_impl(con, definition, person_id, competition_id, season, fixture_id=None, **_):
    """PPDA-style proxy: opponent completed passes allowed per defensive
    action (interception, tackle, sliding tackle) by this player's team,
    restricted to windows where their own team trails by 2+. Lower =
    more intense pressing. Team-level by nature (see methodology doc) —
    scoped to the portion of each window this specific player was on the
    pitch for, same "opposing events, appearance-scoped" pattern as
    psxg_ga's defensive context (step 8) and throw_in_retention_allowed
    (step 9).
    """
    fixture_teams = con.execute(
        "select a.fixture_id, a.team_id, a.start_min, a.end_min from appearance a "
        "join fixture f on f.id = a.fixture_id where a.person_id = ? and f.competition_id = ?",
        [person_id, competition_id],
    ).fetchall()

    opponent_passes = 0
    defensive_actions = 0
    for fid, team_id, start_min, end_min in fixture_teams:
        start_ms, end_ms = start_min * 60000, end_min * 60000
        for w_start, w_end in _trailing_2plus_windows(con, fid, team_id):
            overlap_start, overlap_end = max(start_ms, w_start), min(end_ms, w_end)
            if overlap_end <= overlap_start:
                continue
            row = con.execute(
                "select "
                "sum(case when e.team_id != ? and e.type = 'PASS' and e.outcome = 'COMPLETE' "
                "         then 1 else 0 end), "
                "sum(case when e.team_id = ? and (e.type = 'INTERCEPTION' or "
                f"         (e.type = 'DUEL' and ({foundation.qualifier_contains('Duel', 'GROUND', column='e.qualifiers')}) "
                f"          and not ({foundation.qualifier_contains('Duel', 'LOOSE_BALL', column='e.qualifiers')}))) "
                "then 1 else 0 end) "
                "from event e where e.fixture_id = ? and e.timestamp_ms between ? and ?",
                [team_id, team_id, fid, overlap_start, overlap_end],
            ).fetchone()
            opponent_passes += row[0] or 0
            defensive_actions += row[1] or 0

    value = opponent_passes / defensive_actions if defensive_actions else None
    return MetricResult(value=value, sample_size=defensive_actions)


registry.register("game_state_pressing_intensity_trailing_2plus")(_pressing_intensity_impl)
