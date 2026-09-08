"""Foundation-layer metrics: per-90 counting/rate stats (PHASE-0-BRIEF.md
§7.1, build order step 6), with three switchable adjustments.

Eleven of the fourteen metric ids below (shots, xg, xa, key_passes,
progressive_passes, progressive_carries, duels_won, tackles, interceptions,
recoveries, aerials) are counting stats registered against the same generic
implementation (`_make_count_impl`), parameterised by a `StatSpec` — how to
extract a raw per-fixture value from the `event` table. The other three
(pass_completion_{defensive,middle,attacking}_third) are ratios, not
per-90 rates, and get their own generic implementation. This avoids 14
near-identical Python functions; the YAML/methodology docs are still
one-per-metric, as the brief requires.

`adjustment` is a *runtime* choice (kwarg on the call, threaded through
compute_and_store's **params), not a separate metric id per variant —
matches the brief's "explicit and switchable" language for possession
adjustment, and keeps a single metric_value.definition_id meaningful
across adjustment modes. A metric's YAML `adjustments` list is what modes
it supports; requesting one it doesn't list is a hard error, not a silent
no-op.

Progressive pass/carry definition (ours, since the field has none it fully
agrees on either): moves the ball at least 25% of the remaining distance
to the byline, or ends inside the opponent's box. Box dimensions derived
from a 120x80y pitch normalised to 0-100: x >= 85, 22.5 <= y <= 77.5.

Possession-share proxy: share of a match's open-play events (by count)
belonging to each team — not a stopwatch time-of-possession figure. Feeds
the standard "padj" formula: padj = raw * (50 / team's share that match).

Opposition-strength weight: see `_opponent_strength_weights` — a caveated
proxy, not an independent league-wide rating (see docs/metrics/
opposition_strength_caveat.md).
"""

from collections import defaultdict
from dataclasses import dataclass

from engine.metrics import registry
from engine.metrics.runtime import MetricResult

_PROGRESSIVE_SQL = """
    e.end_x is not null and e.location_x is not null and (
        (100 - e.end_x) <= 0.75 * (100 - e.location_x)
        or (e.end_x >= 85 and e.end_y between 22.5 and 77.5)
    )
"""


@dataclass(frozen=True)
class StatSpec:
    event_where: str  # SQL predicate on the `event` table, aliased `e`
    value_expr: str = "1"  # SQL expression summed per matching row; "1" = count


STAT_SPECS: dict[str, StatSpec] = {
    # Own goals carry an actor_person_id (the scorer) but aren't a shot the
    # player took — excluded so an unlucky deflection doesn't inflate a
    # defender's shot count. xG is unaffected: StatsBomb assigns no xG value
    # to own goals, so they were already invisible to that stat.
    "shots": StatSpec("e.type = 'SHOT' and e.outcome != 'OWN_GOAL'"),
    "xg": StatSpec(
        "e.type = 'SHOT'",
        value_expr="try_cast(json_extract(e.qualifiers, '$.xG') as double)",
    ),
    "xa": StatSpec(
        "e.type = 'PASS' and json_extract_string(e.qualifiers, '$.xA') is not null",
        value_expr="try_cast(json_extract(e.qualifiers, '$.xA') as double)",
    ),
    "key_passes": StatSpec(
        "e.type = 'PASS' and json_extract_string(e.qualifiers, '$.Pass') = 'SHOT_ASSIST'"
    ),
    "progressive_passes": StatSpec(
        f"e.type = 'PASS' and e.outcome = 'COMPLETE' and ({_PROGRESSIVE_SQL})"
    ),
    "progressive_carries": StatSpec(f"e.type = 'CARRY' and ({_PROGRESSIVE_SQL})"),
    "duels_won": StatSpec("e.type = 'DUEL' and e.outcome = 'WON'"),
    "tackles": StatSpec(
        "e.type = 'DUEL' and json_extract_string(e.qualifiers, '$.Duel') "
        "in ('TACKLE', 'SLIDING_TACKLE')"
    ),
    "interceptions": StatSpec("e.type = 'INTERCEPTION'"),
    "recoveries": StatSpec("e.type = 'RECOVERY'"),
    "aerials": StatSpec(
        "e.type = 'DUEL' and json_extract_string(e.qualifiers, '$.Duel') = 'AERIAL' "
        "and e.outcome = 'WON'"
    ),
}

THIRDS = {
    "defensive": (0.0, 100 / 3),
    "middle": (100 / 3, 200 / 3),
    "attacking": (200 / 3, 100.0),
}

ADJUSTMENT_MODES = ("raw", "per_90", "possession", "opposition_strength")


def _appearances(con, person_id: int, competition_id: str) -> list[tuple[int, float, int]]:
    """(fixture_id, minutes, team_id) for every fixture this person played
    in this competition-season."""
    return con.execute(
        "select a.fixture_id, a.minutes, a.team_id "
        "from appearance a join fixture f on f.id = a.fixture_id "
        "where a.person_id = ? and f.competition_id = ?",
        [person_id, competition_id],
    ).fetchall()


def _raw_per_fixture(con, spec: StatSpec, person_id: int, competition_id: str) -> dict[int, float]:
    rows = con.execute(
        f"select e.fixture_id, sum({spec.value_expr}) "
        "from event e "
        "join appearance a on a.fixture_id = e.fixture_id and a.person_id = e.actor_person_id "
        "join fixture f on f.id = e.fixture_id "
        f"where e.actor_person_id = ? and f.competition_id = ? and ({spec.event_where}) "
        "group by e.fixture_id",
        [person_id, competition_id],
    ).fetchall()
    return {fixture_id: value or 0.0 for fixture_id, value in rows}


def _possession_share(con, fixture_id: int, team_id: int) -> float:
    rows = con.execute(
        "select team_id, count(*) from event "
        "where fixture_id = ? and team_id is not null group by team_id",
        [fixture_id],
    ).fetchall()
    counts = dict(rows)
    total = sum(counts.values())
    if not total:
        return 50.0
    return 100.0 * counts.get(team_id, 0) / total


def _opponent_team_id(con, fixture_id: int, own_team_id: int) -> int:
    home_id, away_id = con.execute(
        "select home_team_id, away_team_id from fixture where id = ?", [fixture_id]
    ).fetchone()
    return away_id if own_team_id == home_id else home_id


def _opponent_strength_weights(con, competition_id: str) -> dict[int, float]:
    """xGD-based team quality proxy: each team's own (xG created - xG
    conceded) averaged per match, using only fixtures in this warehouse,
    mapped to a bounded [0.7, 1.3] weight by rank. With a single-club-season
    open-data slice most teams are observed in just their two legs against
    the seed club — this is the best available signal, not an independent
    league-wide rating. See docs/metrics/opposition_strength_caveat.md.
    """
    fixtures = con.execute(
        "select id, home_team_id, away_team_id from fixture where competition_id = ?",
        [competition_id],
    ).fetchall()
    xg_rows = con.execute(
        "select e.fixture_id, e.team_id, "
        "sum(try_cast(json_extract(e.qualifiers, '$.xG') as double)) "
        "from event e join fixture f on f.id = e.fixture_id "
        "where f.competition_id = ? and e.type = 'SHOT' and e.team_id is not null "
        "group by e.fixture_id, e.team_id",
        [competition_id],
    ).fetchall()
    xg_by_fixture_team = {(fid, tid): xg or 0.0 for fid, tid, xg in xg_rows}

    per_match_xgd: dict[int, list[float]] = defaultdict(list)
    for fid, home_id, away_id in fixtures:
        home_xg = xg_by_fixture_team.get((fid, home_id), 0.0)
        away_xg = xg_by_fixture_team.get((fid, away_id), 0.0)
        per_match_xgd[home_id].append(home_xg - away_xg)
        per_match_xgd[away_id].append(away_xg - home_xg)

    avg_xgd = {team_id: sum(vals) / len(vals) for team_id, vals in per_match_xgd.items()}
    ranked = sorted(avg_xgd, key=lambda t: avg_xgd[t])
    n = len(ranked)
    if n <= 1:
        return {team_id: 1.0 for team_id in ranked}
    return {team_id: 0.7 + 0.6 * (rank / (n - 1)) for rank, team_id in enumerate(ranked)}


def _make_count_impl(stat_id: str):
    spec = STAT_SPECS[stat_id]

    def impl(
        con,
        definition,
        person_id: int,
        competition_id: str,
        season: str,
        fixture_id=None,
        adjustment: str = "per_90",
        **_,
    ) -> MetricResult:
        if adjustment not in ADJUSTMENT_MODES:
            raise ValueError(f"unknown adjustment mode '{adjustment}'")
        if adjustment != "raw" and adjustment not in definition.adjustments:
            raise ValueError(
                f"metric '{definition.id}' does not declare support for "
                f"adjustment '{adjustment}' (declares {definition.adjustments})"
            )

        appearances = _appearances(con, person_id, competition_id)
        total_minutes = sum(minutes for _, minutes, _ in appearances)
        raw_per_fixture = _raw_per_fixture(con, spec, person_id, competition_id)

        if adjustment == "possession":
            total = 0.0
            for fid, _, team_id in appearances:
                share = _possession_share(con, fid, team_id)
                factor = (50.0 / share) if share else 1.0
                total += raw_per_fixture.get(fid, 0.0) * factor
        elif adjustment == "opposition_strength":
            weights = _opponent_strength_weights(con, competition_id)
            total = sum(
                raw_per_fixture.get(fid, 0.0)
                * weights.get(_opponent_team_id(con, fid, team_id), 1.0)
                for fid, _, team_id in appearances
            )
        else:
            total = sum(raw_per_fixture.values())

        if adjustment == "raw":
            value = total
        else:
            value = (total / (total_minutes / 90)) if total_minutes else None

        return MetricResult(value=value, sample_size=int(round(total_minutes)))

    return impl


def _make_pass_completion_impl(low: float, high: float):
    def impl(
        con,
        definition,
        person_id: int,
        competition_id: str,
        season: str,
        fixture_id=None,
        adjustment: str | None = None,
        **_,
    ) -> MetricResult:
        if adjustment not in (None, "raw"):
            raise ValueError(
                f"metric '{definition.id}' is a ratio, not a rate — it has no "
                f"'{adjustment}' adjustment (declares {definition.adjustments})"
            )
        upper_bound_sql = "e.location_x <= ?" if high >= 100 else "e.location_x < ?"
        completed, attempts = con.execute(
            "select count(*) filter (where e.outcome = 'COMPLETE'), count(*) "
            "from event e "
            "join appearance a on a.fixture_id = e.fixture_id and a.person_id = e.actor_person_id "
            "join fixture f on f.id = e.fixture_id "
            "where e.actor_person_id = ? and f.competition_id = ? and e.type = 'PASS' "
            f"and e.location_x >= ? and {upper_bound_sql}",
            [person_id, competition_id, low, high],
        ).fetchone()
        value = 100.0 * completed / attempts if attempts else None
        return MetricResult(value=value, sample_size=attempts)

    return impl


for _stat_id in STAT_SPECS:
    registry.register(_stat_id)(_make_count_impl(_stat_id))

for _third_name, (_low, _high) in THIRDS.items():
    registry.register(f"pass_completion_{_third_name}_third")(
        _make_pass_completion_impl(_low, _high)
    )
