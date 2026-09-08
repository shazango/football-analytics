# Opposition-strength weight: a caveated proxy

**This is not an independent, league-wide opponent rating.** Our StatsBomb
open-data ingest covers exactly one club's full season (Bayer Leverkusen,
Bundesliga 2023/24) — every domestic-league open-data release from
StatsBomb is a single-club-season slice, not a full league. We never
observe an opponent's matches against anyone but the seed club. Most
opponents are seen in exactly two matches: their home and away leg against
Leverkusen.

Given that constraint, the only opponent-quality signal available from our
own data is each team's own attacking/defensive output in the matches we
do have — for most teams, just those two legs. This is genuinely weak: a
two-match sample is noisy, and it says as much about how Leverkusen played
that day as about the opponent's real quality.

## The formula

For each team (Leverkusen included, using all 34 of its matches; every
other team, using whichever of its matches appear in this warehouse):

```
xgd(team) = mean over that team's fixtures of (xG created - xG conceded)
```

Teams are ranked by `xgd` and mapped to a bounded weight:

```
weight(team) = 0.7 + 0.6 * (rank / (n_teams - 1))
```

so the weakest observed team gets 0.7, the strongest gets 1.3, and
everyone else falls linearly in between. A player's opposition-adjusted
stat multiplies each fixture's raw count by the *opponent's* weight before
summing and applying per-90.

## Revisit when

A data source that covers a full league table (not just one club's
fixtures) becomes available — e.g. a genuine multi-team ingest, or an
external ratings feed. Until then, treat this adjustment as directionally
suggestive, not authoritative.
