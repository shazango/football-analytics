# game_state_response

**Naming discipline (brief §7.6, verbatim):** this is a game-state
response profile. It is never labelled as a psychological attribute of an
individual. The word "morale" must never appear in code, output, or
documentation — confirmed absent everywhere in this codebase.

Splits foundation metrics by match state (leading/level/trailing by
margin) and by two headline cuts: output in the 10 minutes after
conceding, and pressing intensity when trailing by 2+.

## Scope decision

Applied to a **curated 3-stat subset** — `shots`, `duels_won`, `tackles`
— not all 14 foundation metrics, to keep this step's file count sane.
These three span both the attacking-response and defensive/work-rate
angles the brief's framing implies. `game_state_buckets` in each metric's
own YAML declares which windows it supports; requesting anything else is
an error, same pattern as `adjustments` (step 6).

## Mechanism

`event.game_state` (derived at ingest, step 3) already gives the score
margin for the acting team as of just before that event — reused
directly to classify individual events into `leading` / `level` /
`trailing_1` / `trailing_2plus`. What's new here is the *denominator*:
minutes played within a bucket, which needed a reconstructed team
score-state timeline (goal timestamps aren't stored per-minute anywhere)
intersected against each appearance window — see `_state_breakpoints` /
`minutes_by_margin_bucket` in `engine/metrics/game_state.py`. Verified
against the real warehouse that bucketed minutes sum exactly to a
player's whole-season total minutes.

**After the 10 minutes after conceding** and **pressing intensity when
2+ down** are handled separately from the margin buckets above (they're
time-since-event windows, not score-margin states), each with their own
window-reconstruction from goal events.

**Pressing intensity** is a PPDA-style proxy — opponent completed passes
allowed per defensive action (interception, tackle, sliding tackle) —
restricted to trailing-2+ windows. This is inherently team-level (a
pressing scheme isn't one player's doing), attributed to whichever
players were on the pitch for the relevant window, same pattern as
psxg_ga's defensive context (step 8) and throw_in_retention_allowed
(step 9). Lower value = more intense pressing.

## An honest limitation, not a bug

Bayer Leverkusen went unbeaten all season 2023/24. They spent only 74
events total, across all 34 matches, trailing by 2+ — and were never
behind by 3 or more, even once. Most players will show an
insufficient-sample (or literally zero-sample) result for
`trailing_2plus` and for the pressing-intensity metric — checked directly
against the real warehouse: only a single ~5-minute window across the
whole season qualifies, in one match. That's the correct, honest output
for this specific demo team, not a defect in the mechanism — verified
separately that a player on the pitch during that one window (Patrik
Schick) does get a real, non-null value from it.
