# supply_assisted_xg_share / supply_top_supplier_share / supply_herfindahl_index

"A striker is only as good as his supply" (brief §7.4) — the first
component of system dependency. No adjustments, no confidence intervals:
plain shares/indices over a season's shots.

**Not with-or-without-you analysis.** The brief explicitly says not to
attempt that in Phase 0 — the sample is far too thin (a single club-season
gives at most ~35 matches of data per player). This module only
decomposes existing shots by who supplied them; it makes no claim about
what would happen if a given supplier were unavailable.

## Who supplied a shot?

StatsBomb's own shot-assist/key-pass flag (used by [xa](xa.md) and
[key_passes](key_passes.md)) only covers passes tagged as a *direct* shot
assist. That undercounts: walking back from a shot to find "the event
immediately before it in the same possession chain" turns out to almost
always be the shooter's *own* touch (731 of 916 shots in this warehouse
— receiving the ball, carrying it, adjusting for the strike), not the
teammate who actually created the chance.

Ours instead: walk backward through the shot's own possession chain
looking for the most recent event by a **teammate** (same team, a
different person). The walk stops — the shot counts as **unassisted** —
the moment it hits an **opponent** event that genuinely contests the ball
(`DUEL`, `INTERCEPTION`, `CLEARANCE`, `RECOVERY`, `MISCONTROL`); a bare
opposing `PRESSURE` event doesn't stop it, since applying pressure isn't
touching the ball.

Checked empirically against this warehouse before picking that rule
(916 shots, excluding own goals):

| Rule | Assisted | Unassisted |
|---|---|---|
| Stop at *any* opponent event (too strict) | 45.2% | 54.8% |
| Stop only on a genuine ball contest (**ours**) | 76.9% | 23.1% |
| Never stop, walk the whole chain (too loose) | 95.7% | 4.3% |

The middle rule is the only one that lines up with how the game actually
works: shots are usually the end of a short passing sequence, not a
single isolated touch, but also not "credit whoever touched the ball at
any point in a 40-event possession." 90% of identified suppliers are a
`PASS`, as expected; a small remainder (~7%) are a carry, a duel won, or
a loose ball — accepted as a known edge case of the heuristic, not
specially filtered.

## The three metrics

- **supply_assisted_xg_share**: of a player's total shot xG, what share
  came from assisted shots (vs. self-created chances)? `min_sample: 10`
  (total shots with a known xG value).
- **supply_top_supplier_share**: of a player's *assisted* xG only, what
  share came from their single biggest supplying teammate? High = heavily
  dependent on one creator.
- **supply_herfindahl_index**: sum of squared shares across all suppliers
  (standard concentration index, economics convention: 0-1 scale, not the
  0-10,000 antitrust scale). `1/n_suppliers` (perfectly even) up to `1.0`
  (one supplier creates everything).

Both concentration metrics use `min_sample: 10` **assisted** shots (not
total shots) — with fewer than that, a concentration index is mostly
noise (e.g. 2 assisted shots gives either 0.5 or 1.0, nothing in between).

The full per-supplier breakdown (`supply_breakdown()` in
`engine/metrics/supply.py`) isn't stored — `metric_value` holds one
scalar per metric, not a table. It's there for a future report (step 13)
to render directly.
