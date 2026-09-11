"""SPIKE — not a feature. Throwaway experiment, deliberately outside
src/engine/ and not wired into the report pipeline.

Question: if we derive what each position is *expected* to look like from
the data itself, do the players who diverge sharply point at anything a
football person would care about?

Reads stored metric_value rows only (no re-ingest). Robust scoring:
modified z-score (median / MAD), not mean / stdev, because these
distributions are small and skewed.

    PYTHONPATH=src uv run python spikes/archetype_anomaly.py
    PYTHONPATH=src uv run python spikes/archetype_anomaly.py --include-tackles
"""

import argparse
from statistics import median

from engine.metrics.benchmark import FOUNDATION_STAT_IDS
from engine.metrics.definitions import load_all
from engine.model.db import connect

# Finer than benchmark.py's GK/DF/MF/FW — "what a centre-back looks like"
# and "what a wing-back looks like" are different questions. Collapses
# StatsBomb's left/right/centre variants, which are formation slots, not
# different jobs. L/R Midfield sit in a flat four, so they're wide, not CM.
ARCHETYPES = {
    "Goalkeeper": "GK",
    "Center Back": "CB", "Left Center Back": "CB", "Right Center Back": "CB",
    "Left Back": "FB", "Right Back": "FB",
    "Left Wing Back": "FB", "Right Wing Back": "FB",
    "Center Defensive Midfield": "DM",
    "Left Defensive Midfield": "DM", "Right Defensive Midfield": "DM",
    "Center Midfield": "CM",
    "Left Center Midfield": "CM", "Right Center Midfield": "CM",
    "Center Attacking Midfield": "AM",
    "Left Attacking Midfield": "AM", "Right Attacking Midfield": "AM",
    "Left Wing": "W", "Right Wing": "W",
    "Left Midfield": "W", "Right Midfield": "W",
    "Center Forward": "ST", "Left Center Forward": "ST", "Right Center Forward": "ST",
}

# Iglewicz & Hoaglin's conventional cutoff for the modified z-score.
THRESHOLD = 3.5
# A "distribution" of four players can't tell you what normal looks like.
# Anything thinner than this is reported as unusable rather than scored.
MIN_GROUP = 8
MAD_SCALE = 0.6745  # makes the modified z comparable to a normal z


def latest_values(con, competition_id: str, season: str,
                  relax_min_sample: int | None = None) -> list[dict]:
    """One row per (player, metric): the most recent whole-season value,
    already filtered to sample_size >= the metric's own min_sample.

    `relax_min_sample` overrides that gate — only for the sensitivity
    check on the 450-minute per-90 metrics, which admit so few players
    that no archetype group is scorable at all. Results from a relaxed
    run are not findings; they are a look at whether the gate is what's
    hiding the distribution.
    """
    defs = load_all()
    rows = []
    for stat_id in FOUNDATION_STAT_IDS:
        defn = defs[stat_id]
        min_sample = relax_min_sample if relax_min_sample is not None else defn.min_sample
        adjustment = "per_90" if defn.adjustments else None
        rows += [
            {
                "person_id": pid, "name": name, "position": position,
                "archetype": ARCHETYPES.get(position, "?"),
                "metric": stat_id, "value": value, "sample_size": sample,
                "minutes": minutes, "team": team,
            }
            for pid, name, position, value, sample, minutes, team in con.execute(
                """
                select person_id, canonical_name, primary_position,
                       value, sample_size, minutes, team
                from (
                    select mv.person_id, p.canonical_name, p.primary_position,
                           mv.value, mv.sample_size, m.minutes, m.team,
                           row_number() over (
                               partition by mv.person_id order by mv.computed_at desc
                           ) as rn
                    from metric_value mv
                    join person p on p.id = mv.person_id
                    join (
                        select a.person_id, sum(a.minutes) as minutes,
                               any_value(t.name) as team
                        from appearance a
                        join fixture f on f.id = a.fixture_id
                        join team t on t.id = a.team_id
                        where f.competition_id = ?
                        group by a.person_id
                    ) m on m.person_id = mv.person_id
                    where mv.competition_id = ? and mv.season = ?
                      and mv.definition_id = ? and mv.definition_version = ?
                      and mv.adjustment is not distinct from ?
                      and mv.game_state_bucket is null
                ) latest
                where rn = 1 and value is not null and sample_size >= ?
                """,
                [competition_id, competition_id, season, defn.id, defn.version,
                 adjustment, min_sample],
            ).fetchall()
        ]
    return rows


def score(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Modified z-score of every row against its own archetype+metric
    group. Returns (flagged rows, notes about groups that couldn't be
    scored) — the unscorable groups are as much of the finding as the
    flags are."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        groups.setdefault((row["archetype"], row["metric"]), []).append(row)

    flagged, skipped = [], []
    for (archetype, metric), members in sorted(groups.items()):
        values = [m["value"] for m in members]
        if len(values) < MIN_GROUP:
            skipped.append(f"{archetype}/{metric}: n={len(values)}, below MIN_GROUP={MIN_GROUP}")
            continue
        med = median(values)
        mad = median(abs(v - med) for v in values)
        if mad == 0:
            skipped.append(f"{archetype}/{metric}: n={len(values)}, MAD=0 (no spread to score against)")
            continue
        for member in members:
            z = MAD_SCALE * (member["value"] - med) / mad
            if abs(z) >= THRESHOLD:
                flagged.append({**member, "z": z, "median": med, "mad": mad, "n": len(values)})
    flagged.sort(key=lambda r: abs(r["z"]), reverse=True)
    return flagged, skipped


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--competition-id", default="9-281")
    parser.add_argument("--season", default="2023/2024")
    parser.add_argument("--include-tackles", action="store_true")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--relax-min-sample", type=int, help="sensitivity check only")
    args = parser.parse_args()

    con = connect()
    rows = latest_values(con, args.competition_id, args.season, args.relax_min_sample)
    if not args.include_tackles:
        rows = [r for r in rows if r["metric"] != "tackles"]

    flagged, skipped = score(rows)

    print(f"scored rows: {len(rows)}  players: {len({r['person_id'] for r in rows})}  "
          f"threshold: |modified z| >= {THRESHOLD}  tackles: "
          f"{'in' if args.include_tackles else 'out'}")
    print(f"flags: {len(flagged)}  unscorable groups: {len(skipped)}\n")

    header = f"{'#':>3}  {'player':<24} {'pos':<3} {'min':>6}  {'metric':<32} " \
             f"{'value':>9} {'median':>9} {'z':>7} {'dir':<4} {'n':>3} {'sample':>7}"
    print(header)
    print("-" * len(header))
    for i, r in enumerate(flagged[: args.top], 1):
        print(f"{i:>3}  {r['name'][:24]:<24} {r['archetype']:<3} {r['minutes']:>6.0f}  "
              f"{r['metric']:<32} {r['value']:>9.3f} {r['median']:>9.3f} {r['z']:>7.1f} "
              f"{'HIGH' if r['z'] > 0 else 'LOW':<4} {r['n']:>3} {r['sample_size']:>7}")

    print("\nunscorable groups:")
    for note in skipped:
        print(f"  {note}")


def _self_check() -> None:
    base = {"person_id": 0, "name": "x", "position": "Center Back", "archetype": "CB",
            "metric": "m", "sample_size": 99, "minutes": 900, "team": "t"}
    # Nine identical-ish values plus one far out: only the outlier flags.
    rows = [{**base, "person_id": i, "value": v}
            for i, v in enumerate([1.0, 1.1, 0.9, 1.2, 0.8, 1.0, 1.1, 0.9, 1.0, 9.0])]
    flagged, skipped = score(rows)
    assert not skipped, skipped
    assert [r["value"] for r in flagged] == [9.0], flagged
    # A group under MIN_GROUP is reported, never scored.
    _, skipped = score(rows[:4])
    assert len(skipped) == 1 and "MIN_GROUP" in skipped[0], skipped
    print("self-check ok")


if __name__ == "__main__":
    import sys
    if "--self-check" in sys.argv:
        _self_check()
    else:
        main()
