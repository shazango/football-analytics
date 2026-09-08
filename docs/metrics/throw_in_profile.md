# throw_in_profile

Throw-ins are logged by every provider and derived by none (brief §7.3).
StatsBomb doesn't tag them as their own event type — they're `PASS` events
with `qualifiers.SetPiece = 'THROW_IN'`. 1079 in the Bundesliga 2023/24
season (34 matches), ~31.7/match.

No adjustments, no confidence intervals — every metric here is a plain
share or mean over throws taken (or faced), not a per-90 rate.

## Operational definitions

The brief names the shape (fast/long/clever, retention under pressure,
defensive mirror) but not exact thresholds — same situation as
progressive-pass (step 6). Ours, checked empirically against this
warehouse before picking them:

- **Fast**: time from the preceding `BALL_OUT` event to the throw ≤ 8
  seconds. Median time is ~11.5s league-wide, so 8s selects a genuine
  minority of quick restarts (~33%), not "roughly average."
- **Pressed**: an opposing-team `PRESSURE` event occurs in the same
  possession chain within 8 seconds of the throw. StatsBomb's own
  `UnderPressure` qualifier is essentially never set on throw-ins (2 of
  1079 in this warehouse) — unusable as the brief's headline signal, so
  this proxy replaces it. Flags 521 of 1079 throws (48%) as pressed.
- **Retained**: the possession chain the throw starts lasts at least 5
  seconds, or ends in a shot by the throwing team, before the ball
  changes possession — whichever comes first. 5s sits below the median
  chain duration (~13.7s) but above the 25th percentile (~4.8s), so it
  separates a real minority of quick turnovers from sustained possession
  rather than splitting down the middle.

## The six metrics

- **throw_in_retention_under_pressure** (headline, brief §7.3): retention
  rate restricted to *pressed* throws only. `min_sample: 15` (pressed
  throws, not all throws — a lower bar since only ~48% of throws qualify).
- **throw_in_retention_rate**: retention rate across all throws, for
  context against the pressured number.
- **throw_in_distance**: mean straight-line distance from throw location
  to end location.
- **throw_in_territory_gained**: mean forward progress (`end_x - location_x`
  in our normalised 0-100 coordinates, oriented toward the attacking goal
  — see `engine/model/schema.py`). Can be negative (a sideways/backward
  throw).
- **throw_in_aerial_win_rate**: among throws with an aerial duel in the
  same possession chain (13.3% of all throws — "Long" throws contested in
  the air), the share the throwing team wins. `min_sample: 5`, reflecting
  the much smaller contested-throw population.
- **throw_in_retention_allowed** (defensive mirror): retention rate of the
  *opponent's* throw-ins, across every fixture this player appeared in —
  same "opposing shots" pattern as psxg_ga's defensive context (step 8),
  applied to throws instead. Substitution timing ignored, same
  simplification as step 8.
- **throw_in_clever_share** ("Clever"): share of throws where either the
  throw itself, or the first receiver's next touch, bypasses at least one
  opponent — reusing `line_break_value`'s bypass detection directly (step
  11; deferred until that metric existed). Grimaldo (Leverkusen's primary
  thrower, 197 throws that season): 21.3%.
