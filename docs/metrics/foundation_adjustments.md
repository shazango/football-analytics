# Foundation-layer adjustments

Shared methodology for the three adjustment modes available to every
foundation-layer counting stat (PHASE-0-BRIEF.md §7.1). `adjustment` is a
runtime choice on each call, not a separate metric id — a metric's YAML
`adjustments` list is what it supports; requesting anything else is an error.

Sample size for all four modes below is minutes played in the
competition-season (default threshold 450, per metric YAML `min_sample`).

## `raw`
The unadjusted season total. No minutes scaling.

## `per_90`
`raw_total / (total_minutes / 90)`. The baseline rate stat.

## `possession`
Corrects for a simple fact: a player on a low-possession team touches the
ball less, so their counting stats look smaller regardless of ability.

Our possession-share proxy: **share of a match's open-play events (by
count) belonging to each team.** Not a stopwatch time-of-possession figure
— we don't have one. This is an explicit, documented choice, not a silent
pick from among several competing "possession %" definitions the industry
actually uses.

Formula (the standard "padj" adjustment): for each fixture, scale that
fixture's raw count by `50 / team_possession_share_pct_in_that_fixture`,
then sum across fixtures and apply `per_90` as normal. A team with above
average (>50%) possession has its players' raw counts scaled down; a team
with below-average possession has them scaled up.

## `opposition_strength`
Weight each match by opponent quality — see
[opposition_strength_caveat.md](opposition_strength_caveat.md) for the
weight formula and, more importantly, why it's a weak proxy in Phase 0
specifically.
