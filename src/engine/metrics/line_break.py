"""line_break_value (PHASE-0-BRIEF.md §7.5, build order step 11).

Weights a completed pass by how many opposition outfield players it
removes from between the ball and the goal ("packing", in the industry
term Impect's own open data uses), weighted by how close each removed
player was to goal. Validated against Impect's open-data packing/
packing-xG numbers for the same players — see
docs/metrics/line_break_value.md and engine/ingest/impect.py.

Every completed pass with a freeze frame is evaluated (76.9% of completed
passes in this warehouse have one) — not only ones already flagged
`progressive` by the step-6 foundation metric, since a pass can remove a
defender from the game without satisfying that metric's distance
threshold (e.g. a pass played square that still bypasses a covering
defender who was goal-side of the ball).

**Bypassed**: an opposing outfield player (goalkeepers excluded — see
methodology) who was between the ball and the goal before the pass
(`x > start_x`, our normalised coordinates, `x` toward the attacking goal)
and no longer is after it (`x <= end_x`).

**Weight**: `opponent_x / 100` — a bypassed player closer to goal is worth
more, same spirit as Impect's packing-xG, without claiming to replicate
their (proprietary, unpublished) exact model.
"""

import json

from engine.metrics import registry
from engine.metrics.foundation import _appearances
from engine.metrics.runtime import MetricResult

ADJUSTMENT_MODES = ("raw", "per_90")


def _bypassed_value_and_count(location_x: float, end_x: float, freeze_frame: list[dict]) -> tuple[float, int]:
    value = 0.0
    count = 0
    for p in freeze_frame:
        if p["teammate"] or p["keeper"]:
            continue
        if p["x"] > location_x and p["x"] <= end_x:
            value += p["x"] / 100.0
            count += 1
    return value, count


def _passes_with_value(con, person_id: int, competition_id: str) -> list[tuple[float, int]]:
    """(value, bypassed_count) for every completed pass this person made
    with a freeze frame available."""
    rows = con.execute(
        "select e.location_x, e.end_x, e.freeze_frame "
        "from event e join fixture f on f.id = e.fixture_id "
        "where e.actor_person_id = ? and f.competition_id = ? and e.type = 'PASS' "
        "and e.outcome = 'COMPLETE' and e.freeze_frame is not null",
        [person_id, competition_id],
    ).fetchall()
    out = []
    for location_x, end_x, freeze_frame_json in rows:
        freeze_frame = json.loads(freeze_frame_json)
        if freeze_frame is None or end_x is None:
            continue
        out.append(_bypassed_value_and_count(location_x, end_x, freeze_frame))
    return out


def _line_break_value_impl(con, definition, person_id, competition_id, season,
                            fixture_id=None, adjustment="per_90", **_):
    if adjustment not in ADJUSTMENT_MODES:
        raise ValueError(f"unknown adjustment mode '{adjustment}'")
    if adjustment != "raw" and adjustment not in definition.adjustments:
        raise ValueError(
            f"metric '{definition.id}' does not declare support for "
            f"adjustment '{adjustment}' (declares {definition.adjustments})"
        )

    passes = _passes_with_value(con, person_id, competition_id)
    total_value = sum(value for value, _ in passes)
    total_minutes = sum(minutes for _, minutes, _ in _appearances(con, person_id, competition_id))

    if adjustment == "raw":
        value = total_value
    else:
        value = (total_value / (total_minutes / 90)) if total_minutes else None

    # Minutes, not completed passes — the same exposure measure every
    # other per-90 metric reports (foundation._per_90_stat). Gating a
    # per-90 rate on pass count admits a single high-possession match:
    # Eric Dier cleared a 20-pass threshold with 91 completed passes in
    # one 98-minute appearance and benchmarked as a season-long outlier
    # at a per-pass value (0.93) indistinguishable from Xhaka's (1.01).
    return MetricResult(value=value, sample_size=int(round(total_minutes)))


registry.register("line_break_value")(_line_break_value_impl)
