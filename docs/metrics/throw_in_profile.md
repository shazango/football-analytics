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
- **throw_in_retention_allowed** (defensive mirror, **team-level — not on
  player reports**): retention rate of the
  *opponent's* throw-ins, across every fixture this player appeared in —
  same "opposing shots" pattern as psxg_ga's defensive context (step 8),
  applied to throws instead. Substitution timing ignored, same
  simplification as step 8.
- **throw_in_clever_share** ("Clever"): share of throws where either the
  throw itself, or the first receiver's next touch, bypasses at least one
  opponent — reusing `line_break_value`'s bypass detection directly (step
  11; deferred until that metric existed). Grimaldo (Leverkusen's primary
  thrower, 197 throws that season): 21.3%.

## Why throw_in_retention_allowed is not on the player report

It measures the opponents' throw-ins across every fixture the player
appeared in. The player's own actions never enter the calculation, so the
only thing that varies between teammates is which matches they played.

On the Bundesliga 2023/24 slice all 24 Leverkusen players who have a
value sit in a narrow band, and the ten with the most minutes span 2.1
percentage points:

| Player | n | Value |
|---|---|---|
| Hrádecký | 492 | 69.9% |
| Tah | 468 | 70.1% |
| Frimpong | 465 | 69.9% |
| Xhaka | 485 | 68.7% |
| Wirtz | 476 | 68.7% |
| Andrich | 419 | 68.0% |

The full range across the squad is 40.0-77.0, and that spread comes
entirely from players with few appearances and small denominators — noise
in the sample, not a property of the player.

It was rendering on every individual report at effectively the same
value. Labelling it "(team)" and leaving it in place would have been
worse than removing it: a row the reader has to learn to ignore on every
report costs attention on every report. The metric is a real measurement
of how a side defends opposition throws and is retained for a team page.
