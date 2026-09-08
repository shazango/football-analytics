"""Benchmark sets (PHASE-0-BRIEF.md §8, build order step 7): the full
distribution of every foundation metric across all qualifying players, by
competition/season/position bucket. First-class and stored, not a helper
computed fresh for each report — see `benchmark_distribution` in schema.py.

Two steps, deliberately separate:
1. `compute_roster_metrics` — run every foundation metric for every player
   who appeared this competition-season, storing metric_value rows (a
   batch driver over the per-player runtime built in steps 5-6).
2. `compute_benchmark` — read those stored values back, grouped by
   position bucket, and snapshot the distribution.

Position bucketing: StatsBomb's `primary_position` is granular (23 distinct
labels in the Bundesliga 2023/24 slice) and, at that granularity, almost no
bucket has more than one or two players clearing `min_sample` — a
"distribution" of one point can't show where anyone sits. Bucketed here
into the conventional four: GK / DF / MF / FW.
"""

import json
from datetime import datetime, timezone

from engine.metrics.runtime import compute_and_store

POSITION_BUCKETS: dict[str, str] = {
    "Goalkeeper": "GK",
    "Center Back": "DF",
    "Left Center Back": "DF",
    "Right Center Back": "DF",
    "Left Back": "DF",
    "Right Back": "DF",
    "Left Wing Back": "DF",
    "Right Wing Back": "DF",
    "Center Defensive Midfield": "MF",
    "Left Defensive Midfield": "MF",
    "Right Defensive Midfield": "MF",
    "Center Midfield": "MF",
    "Left Center Midfield": "MF",
    "Right Center Midfield": "MF",
    "Center Attacking Midfield": "MF",
    "Left Attacking Midfield": "MF",
    "Right Attacking Midfield": "MF",
    "Left Midfield": "MF",
    "Right Midfield": "MF",
    "Center Forward": "FW",
    "Left Center Forward": "FW",
    "Right Center Forward": "FW",
    "Left Wing": "FW",
    "Right Wing": "FW",
}
UNKNOWN_BUCKET = "Unknown"


def position_bucket(primary_position: str | None) -> str:
    if primary_position is None:
        return UNKNOWN_BUCKET
    return POSITION_BUCKETS.get(primary_position, UNKNOWN_BUCKET)


def roster_person_ids(con, competition_id: str) -> list[int]:
    return [
        row[0]
        for row in con.execute(
            "select distinct person_id from appearance a "
            "join fixture f on f.id = a.fixture_id where f.competition_id = ?",
            [competition_id],
        ).fetchall()
    ]


def compute_roster_metrics(
    con,
    definitions: dict,
    competition_id: str,
    season: str,
    adjustment: str = "per_90",
) -> None:
    """Compute and store every given metric for every player who appeared
    in this competition-season. Ratio metrics (declaring no adjustments)
    get `adjustment=None` regardless of what's requested here — they have
    no adjustment concept, that's the caller's problem to know, not
    something to silently coerce.
    """
    person_ids = roster_person_ids(con, competition_id)
    for definition in definitions.values():
        metric_adjustment = adjustment if definition.adjustments else None
        for person_id in person_ids:
            compute_and_store(
                con,
                definition,
                person_id=person_id,
                competition_id=competition_id,
                season=season,
                adjustment=metric_adjustment,
            )


def compute_benchmark(
    con,
    definition,
    competition_id: str,
    season: str,
    bucket: str,
    adjustment: str | None = None,
    game_state_bucket: str | None = None,
) -> dict:
    """Distribution of one metric's latest computed value across all
    qualifying players (sample_size >= min_sample) in one position bucket.
    Stores a snapshot row in benchmark_distribution; returns {n, values}.

    `game_state_bucket` (step 12) must be filtered the same way as
    `adjustment` — a definition_id like "shots" can have both whole-season
    rows (game_state_bucket NULL) and state-scoped rows coexisting; without
    this filter "latest computed_at per person" could pick either kind.
    """
    rows = con.execute(
        """
        select value, primary_position from (
            select mv.value, mv.sample_size, p.primary_position,
                   row_number() over (
                       partition by mv.person_id order by mv.computed_at desc
                   ) as rn
            from metric_value mv
            join person p on p.id = mv.person_id
            where mv.competition_id = ? and mv.season = ?
              and mv.definition_id = ? and mv.definition_version = ?
              and mv.adjustment is not distinct from ?
              and mv.game_state_bucket is not distinct from ?
        ) latest
        where rn = 1 and value is not null and sample_size >= ?
        """,
        [competition_id, season, definition.id, definition.version, adjustment,
         game_state_bucket, definition.min_sample],
    ).fetchall()

    values = sorted(value for value, position in rows if position_bucket(position) == bucket)
    n = len(values)
    con.execute(
        "INSERT INTO benchmark_distribution VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            competition_id,
            season,
            bucket,
            definition.id,
            definition.version,
            adjustment,
            n,
            json.dumps(values),
            datetime.now(timezone.utc),
        ],
    )
    return {"n": n, "values": values}


def percentile_rank(distribution_values: list[float], value: float) -> float:
    """Share of the distribution at or below `value`, in [0, 1]. Sorted
    input assumed (as stored). Used by reports (step 13) to place a player
    within their benchmark; kept here since it's meaningless without the
    distribution shape this module produces."""
    if not distribution_values:
        return float("nan")
    below_or_equal = sum(1 for v in distribution_values if v <= value)
    return below_or_equal / len(distribution_values)
