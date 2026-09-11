# line_break_value

Weights a completed pass by how many opposition outfield players it
removes from between the ball and the goal — "packing," in the term
Impect's own open data uses — weighted by how close each removed player
was to goal (brief §7.5). Reported per-90; `min_sample: 450` minutes.

## Why the sample gate is in minutes (v2)

v1 gated on 20 completed passes with a freeze frame. That is the wrong
denominator for a per-90 rate: pass volume is a property of the team's
possession share, not of the player's exposure, so one high-possession
appearance clears it. Eric Dier completed 91 passes in a single 98-minute
match and benchmarked as a season-long outlier (78.4 per 90, top of 57
centre-backs) at a per-pass value of 0.93 — statistically indistinguishable
from Xhaka's 0.99 over 2,481 passes. The rate was real; the sample behind
it was one game.

v2 gates on 450 minutes, the same exposure measure every other per-90
metric uses (`foundation._per_90_stat`). `sample_size` is now minutes
played, not passes evaluated.

The cost is comparison-set breadth. In a single-club slice no opposition
player reaches 450 minutes — they face Leverkusen twice, ~200 minutes at
most — so the benchmark population drops from 61 players across 17 clubs
to the 18 Leverkusen players who clear the threshold. That is the same
restriction every other per-90 metric already carries; v1 was the
exception, and it bought its breadth by admitting one-match samples.
Multi-club data removes the trade-off.

## Detection

Every completed pass with a freeze frame is evaluated, not only ones
already flagged `progressive` by the foundation-layer metric of that name
(step 6) — a pass can remove a defender from the game without covering
25% of the remaining distance to goal (e.g. a short pass played through
a gap that a purely distance-based rule would miss).

An opposing outfield player (goalkeepers excluded — see below) counts as
**bypassed** if they were between the ball and the goal before the pass
(`x > location_x`, our normalised 0-100 coordinates, `x` toward the
attacking goal) and no longer are after it (`x <= end_x`). Weight:
`opponent_x / 100` — closer to goal is worth more, the simplest possible
reading of "weighted by position relative to goal." This is a documented
choice, not a claim to replicate Impect's own (proprietary, unpublished)
weighting.

Goalkeepers are excluded from the bypassed-player count: packing is about
removing a defender from the defensive shape, not "reaching the last
line," which the metric already rewards via the position weight itself.

## Validation against Impect

Impect's open-data release publishes per-player, per-match KPIs including
`BYPASSED_OPPONENTS` (a raw packing count) and `PACKING_XG` (their
non-shot xG model, which — per their own KPI definition — folds packing
together with distance to goal, angle, pressure, body part, and phase of
play). It covers the entire Bundesliga 2023/24 season (306 matches, all
18 clubs) as one dataset ("iteration" 743) — we only need the 34 matches
involving Bayer Leverkusen, to match what's already ingested.

**Fixture alignment.** No shared match id exists between providers
(Impect's `idMappings` carry `heim_spiel`/`skill_corner` references, not
StatsBomb). Both providers list exactly 34 Leverkusen 2023/24 matches;
sorting each by date and pairing them 1:1 lines up cleanly — verified
that the first pair (2023-08-19, Leverkusen home vs. RB Leipzig on both
sides) matches on date and opponent identity. See `align_fixtures` in
`engine/ingest/impect.py`.

**Player resolution**, using the step-4 identity module as designed:
`resolve_person(source="impect", ...)` against Impect's `commonname` +
`birthdate`. Our own `person.dob` is always NULL (StatsBomb's open data
doesn't include it), so this is name-only matching in practice. **9 of
17** Leverkusen players with 450+ minutes resolved cleanly; the other 8
(Hrádecký, Grimaldo, Palacios, Tapsoba, Boniface, Kossonou, Hincapié,
Stanišić, Hložek) didn't, because Impect's `commonname` is a shortened
form (e.g. "Alejandro Grimaldo") against StatsBomb's full legal name
("Alejandro Grimaldo García"). Per brief §5, this is a real, correctly
unresolved mismatch, not a bug — building fuzzy/partial-name matching to
force these through is explicitly out of scope for Phase 0. Opponents'
players are excluded from validation entirely: our own event data only
covers their 1-2 matches against Leverkusen, against Impect's full-season
figures for the same player — an apples-to-oranges scope mismatch.

**Result**, aggregated across the same 34 matches for the 9 resolved
players:

| Comparison | Pearson r | Spearman r |
|---|---|---|
| Our raw bypass count vs. Impect `BYPASSED_OPPONENTS` | **0.97** | 0.97 |
| Our weighted value vs. Impect `PACKING_XG` | -0.44 | -0.42 |

The raw-count correlation is strong and is the real validation: our core
bypass-detection logic finds essentially the same events Impect's does.

The weighted-value correlation is not just weak but *negative* — and
that's expected once you look at what `PACKING_XG` actually measures.
Checking the two lowest- and two highest-`PACKING_XG` players in the
sample: Xhaka (deep-lying playmaker) bypasses the *most* opponents of
anyone (2084.5) but has the *second-lowest* `PACKING_XG` (1.82); Tah
(centre-back) is similar (1668.2 bypassed, 0.97 pxg). Frimpong, Wirtz,
Hofmann, and Schick — all attacking players — score highest on
`PACKING_XG` (7-11) despite far lower bypass counts. `PACKING_XG` is a
**danger-created** model, not a rescaled packing count: it rewards
reaching threatening positions, weighted heavily toward the final third,
not the raw act of removing a defender from deep buildup play. Our
`line_break_value` only claims the narrower thing brief §7.5 actually
asks for — position-weighted packing — so a strong correlation against a
broader shot-danger model was never a realistic bar, and its absence
doesn't undermine the raw-count validation above.

## Caveats

- n=9 for the correlation check — small, but it's every Leverkusen player
  with enough minutes whose name resolved cleanly across both providers.
- The `opponent_x / 100` weighting is ours, explicit, and simple by
  design — not a reconstruction of any specific published packing-xG
  model.
