"""Player Report intermediate representation (PHASE-0-BRIEF.md §9, build
order step 13).

One player, one competition, one season. `build_report` is the *only*
place that touches the database or computes anything — the three
renderers (json_renderer.py, xlsx_renderer.py, pdf_renderer.py) are pure
projections of the dict it returns, never recomputing a value (brief §9:
"renderers must not recompute anything").

Suppressing sub-`min_sample` values is a rendering decision (brief §6),
not something baked into this IR: every field here carries the raw
value/sample_size/min_sample so a renderer can decide how to display it
(JSON shows everything, including below-threshold values, per §9: "same
projection plus definition ids and versions"; XLSX/PDF show "insufficient
sample" instead — see those renderers).
"""

from datetime import datetime, timezone

from engine.metrics import (  # noqa: F401 (registers implementations)
    foundation,
    game_state,
    line_break,
    psxg,
    supply,
    throw_in,
)
from engine.metrics.benchmark import (
    FOUNDATION_STAT_IDS,
    MIN_BENCHMARK_N,
    compute_benchmark,
    percentile_rank,
    position_bucket,
)
from engine.metrics.definitions import load_all
from engine.metrics.runtime import compute_and_store
from engine.render.claims import benchmark_stats, build_claims, load_bands
from engine.render.format import comparison_short, format_value

ATTRIBUTION = (
    "Data: StatsBomb Open Data "
    "(https://github.com/statsbomb/open-data), used under their Open Data User Agreement."
)

GK_PANEL_STAT_IDS = [
    "psxg_ga", "defensive_xg_per_shot_faced",
    "defensive_shots_central_share", "defensive_shots_unpressured_share",
]
FW_PANEL_STAT_IDS = ["supply_assisted_xg_share", "supply_top_supplier_share", "supply_herfindahl_index"]
THROW_IN_STAT_IDS = [
    "throw_in_retention_under_pressure", "throw_in_retention_rate", "throw_in_distance",
    "throw_in_territory_gained", "throw_in_aerial_win_rate", "throw_in_clever_share",
    "throw_in_retention_allowed",
]
GAME_STATE_STAT_IDS = ["shots", "duels_won", "tackles"]
GAME_STATE_BUCKETS = ["leading", "level", "trailing_1", "trailing_2plus", "after_conceding_10min"]


def _metric_entry(con, defn, person_id, competition_id, season, adjustment=None) -> dict:
    result = compute_and_store(
        con, defn, person_id=person_id, competition_id=competition_id, season=season,
        adjustment=adjustment,
    )
    return {
        "id": defn.id,
        "title": defn.title,
        "value": result.value,
        "sample_size": result.sample_size,
        "min_sample": defn.min_sample,
        "suppressed": result.sample_size < defn.min_sample,
        "ci_low": result.ci_low,
        "ci_high": result.ci_high,
        "confidence": defn.confidence,
        "adjustment": adjustment,
        "unit": defn.unit,
        # The one string every renderer prints. A bootstrap metric's
        # interval is built into it, so "never a bare point estimate"
        # (brief §6) holds without each renderer remembering to check.
        "display_value": format_value(
            result.value, defn.unit, adjustment, result.ci_low, result.ci_high
        ),
        "methodology": defn.methodology,
        "definition_version": defn.version,
        "computed_at": result.computed_at,
        "input_hash": result.input_hash,
    }


def _with_benchmark(con, entry: dict, defn, competition_id, season, bucket, adjustment=None) -> dict:
    dist = compute_benchmark(con, defn, competition_id, season, bucket, adjustment=adjustment)
    entry["benchmark_n"] = dist["n"]
    entry["benchmark_min_n"] = MIN_BENCHMARK_N
    # Same shape as "suppressed" above: the IR carries the number and says
    # it shouldn't be shown, rather than deciding that for the renderers.
    entry["benchmark_suppressed"] = dist["n"] < MIN_BENCHMARK_N
    entry["benchmark_percentile"] = (
        percentile_rank(dist["values"], entry["value"])
        if entry["value"] is not None and dist["values"]
        else None
    )
    # Median/MAD/rank: what a claim needs to say *what* the player is being
    # compared against, not only where they finished in it.
    entry.update(benchmark_stats(dist["values"], entry["value"]))
    entry["benchmark_comparison"] = comparison_short(entry)
    entry["benchmark_median_display"] = format_value(
        entry["benchmark_median"], entry.get("unit"), entry.get("adjustment")
    )
    return entry


def build_report(con, person_id: int, competition_id: str, season: str) -> dict:
    defs = load_all()

    person_row = con.execute(
        "select canonical_name, primary_position from person where id = ?", [person_id]
    ).fetchone()
    if person_row is None:
        raise ValueError(f"no person with id {person_id}")
    name, primary_position = person_row
    bucket = position_bucket(primary_position)

    competition_row = con.execute(
        "select name, season from competition where id = ?", [competition_id]
    ).fetchone()
    comp_name, comp_season = competition_row

    total_minutes = sum(
        m for (m,) in con.execute(
            "select a.minutes from appearance a join fixture f on f.id = a.fixture_id "
            "where a.person_id = ? and f.competition_id = ?",
            [person_id, competition_id],
        ).fetchall()
    )

    foundation_metrics = []
    for stat_id in FOUNDATION_STAT_IDS:
        defn = defs[stat_id]
        adjustment = "per_90" if defn.adjustments else None
        entry = _metric_entry(con, defn, person_id, competition_id, season, adjustment)
        _with_benchmark(con, entry, defn, competition_id, season, bucket, adjustment)
        foundation_metrics.append(entry)

    position_panel = None
    if bucket == "GK":
        position_panel = [
            _metric_entry(con, defs[sid], person_id, competition_id, season,
                          "per_90" if defs[sid].adjustments else None)
            for sid in GK_PANEL_STAT_IDS
        ]
    elif bucket == "FW":
        position_panel = [
            _metric_entry(con, defs[sid], person_id, competition_id, season)
            for sid in FW_PANEL_STAT_IDS
        ]

    throw_in_entries = [_metric_entry(con, defs[sid], person_id, competition_id, season)
                         for sid in THROW_IN_STAT_IDS]
    throw_in_profile = throw_in_entries if any(e["sample_size"] > 0 for e in throw_in_entries) else None

    game_state_response = []
    for stat_id in GAME_STATE_STAT_IDS:
        defn = defs[stat_id]
        for gs_bucket in GAME_STATE_BUCKETS:
            result = compute_and_store(
                con, defn, person_id=person_id, competition_id=competition_id, season=season,
                adjustment="per_90", game_state_bucket=gs_bucket,
            )
            game_state_response.append({
                "stat_id": stat_id,
                "bucket": gs_bucket,
                "value": result.value,
                "sample_size": result.sample_size,
                "min_sample": defn.min_sample,
                "suppressed": result.sample_size < defn.min_sample,
                "display_value": format_value(
                    result.value, defn.unit, "per_90", result.ci_low, result.ci_high
                ),
                "computed_at": result.computed_at,
                "input_hash": result.input_hash,
            })

    return {
        "person_id": person_id,
        "name": name,
        "primary_position": primary_position,
        "position_bucket": bucket,
        "competition": {"id": competition_id, "name": comp_name, "season": comp_season},
        "minutes": total_minutes,
        "foundation_metrics": foundation_metrics,
        "claims": build_claims(foundation_metrics, bucket, load_bands()),
        "position_panel": position_panel,
        "throw_in_profile": throw_in_profile,
        "game_state_response": game_state_response,
        "attribution": ATTRIBUTION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _main() -> None:
    import argparse

    from engine.model.db import connect
    from engine.render.json_renderer import render_json
    from engine.render.xlsx_renderer import render_xlsx

    parser = argparse.ArgumentParser()
    parser.add_argument("--player", required=True, type=int, help="person_id")
    parser.add_argument("--competition-id", default="9-281")
    parser.add_argument("--season", default="2023/2024")
    args = parser.parse_args()

    con = connect()
    report = build_report(con, args.player, args.competition_id, args.season)
    con.commit()

    from pathlib import Path
    out_dir = Path("out")
    out_dir.mkdir(exist_ok=True)
    stem = out_dir / str(args.player)

    from engine.render.pdf_renderer import render_pdf

    render_json(report, stem.with_suffix(".json"))
    render_xlsx(report, stem.with_suffix(".xlsx"))
    render_pdf(report, stem.with_suffix(".pdf"))
    print(f"Wrote {stem}.json, {stem}.xlsx, {stem}.pdf")


if __name__ == "__main__":
    _main()
