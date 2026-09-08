"""supply_attribution (PHASE-0-BRIEF.md §7.4, build order step 10).

Decomposes a player's shot xG by which teammate supplied it, using
possession chains — not StatsBomb's own shot-assist/key-pass flag (see
xa.md), since the event immediately preceding a shot is overwhelmingly the
shooter's *own* touch (731 of 916 shots in this warehouse receive the ball,
carry, or otherwise touch it themselves right before shooting), not the
actual supplier.

Supplier definition (ours — the brief doesn't give one, same situation as
progressive-pass/throw-in thresholds): walking backward through the shot's
own possession chain, the supplier is the most recent event by a teammate
(same team, different person). The walk stops — the shot counts as
unassisted — as soon as it hits an *opponent* event that genuinely
contests the ball (duel, interception, clearance, recovery, miscontrol);
a bare opposing PRESSURE event doesn't stop the walk, since it doesn't
represent a touch. Checked empirically before picking this rule: it finds
a supplier for 76.9% of shots, against 45.2% for the strictest version
(stop at any opponent event at all) and 95.7% for the loosest (never
stop, walk the whole chain) — see docs/metrics/supply_attribution.md.

Per brief: do not attempt with-or-without-you analysis in Phase 0 — the
sample is far too thin. Not attempted here.
"""

from engine.metrics import registry
from engine.metrics.runtime import MetricResult

BALL_CONTEST_TYPES = {"DUEL", "INTERCEPTION", "CLEARANCE", "RECOVERY", "MISCONTROL"}


def _find_supplier(con, fixture_id: int, sequence: int, possession_id: int,
                    shooter_id: int, team_id: int) -> int | None:
    candidates = con.execute(
        "select type, actor_person_id, team_id from event "
        "where fixture_id = ? and possession_id = ? and sequence < ? "
        "order by sequence desc",
        [fixture_id, possession_id, sequence],
    ).fetchall()
    for event_type, actor_id, event_team_id in candidates:
        if event_team_id == team_id and actor_id is not None and actor_id != shooter_id:
            return actor_id
        if event_team_id != team_id and event_type in BALL_CONTEST_TYPES:
            return None
    return None


def _shots_with_xg(con, person_id: int, competition_id: str) -> list[tuple[float, int | None]]:
    """(xg, supplier_person_id_or_None) for every shot this person took,
    excluding own goals and shots StatsBomb assigned no xG value."""
    rows = con.execute(
        "select e.fixture_id, e.sequence, e.team_id, e.possession_id, "
        "try_cast(json_extract(e.qualifiers, '$.xG') as double) as xg "
        "from event e join fixture f on f.id = e.fixture_id "
        "where e.actor_person_id = ? and f.competition_id = ? and e.type = 'SHOT' "
        "and e.outcome != 'OWN_GOAL'",
        [person_id, competition_id],
    ).fetchall()
    out = []
    for fixture_id, sequence, team_id, possession_id, xg in rows:
        if xg is None:
            continue
        supplier = _find_supplier(con, fixture_id, sequence, possession_id, person_id, team_id)
        out.append((xg, supplier))
    return out


def supply_breakdown(con, person_id: int, competition_id: str) -> dict[int | None, float]:
    """Full decomposition: {supplier_person_id or None (unassisted): total
    xG supplied}. Not stored in metric_value (a scalar-per-metric table)
    — this is the full breakdown a report (step 13) would render as a
    table/chart; the summary metrics below are derived from it."""
    breakdown: dict[int | None, float] = {}
    for xg, supplier in _shots_with_xg(con, person_id, competition_id):
        breakdown[supplier] = breakdown.get(supplier, 0.0) + xg
    return breakdown


def _make_supply_impl(kind: str):
    def impl(con, definition, person_id, competition_id, season, fixture_id=None, **_):
        shots = _shots_with_xg(con, person_id, competition_id)
        n_total = len(shots)
        assisted = [(xg, supplier) for xg, supplier in shots if supplier is not None]
        n_assisted = len(assisted)
        assisted_xg = sum(xg for xg, _ in assisted)
        total_xg = sum(xg for xg, _ in shots)

        if kind == "assisted_xg_share":
            value = 100.0 * assisted_xg / total_xg if total_xg else None
            return MetricResult(value=value, sample_size=n_total)

        by_supplier: dict[int, float] = {}
        for xg, supplier in assisted:
            by_supplier[supplier] = by_supplier.get(supplier, 0.0) + xg

        if kind == "top_supplier_share":
            value = 100.0 * max(by_supplier.values()) / assisted_xg if by_supplier else None
        else:  # herfindahl_index
            value = (
                sum((v / assisted_xg) ** 2 for v in by_supplier.values()) if by_supplier else None
            )
        return MetricResult(value=value, sample_size=n_assisted)

    return impl


registry.register("supply_assisted_xg_share")(_make_supply_impl("assisted_xg_share"))
registry.register("supply_top_supplier_share")(_make_supply_impl("top_supplier_share"))
registry.register("supply_herfindahl_index")(_make_supply_impl("herfindahl_index"))
