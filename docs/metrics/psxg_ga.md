# psxg_ga

Post-shot expected goals minus goals allowed. Positive means the keeper
prevented more goals than an average keeper would have, facing the exact
same shots; negative means the reverse. Reported per-90 with a bootstrap
confidence interval — shot-stopping is high variance over a season's worth
of shots, and a bare point estimate is misleading (brief §7.2).

## Post-shot xG vs. pre-shot xG

The `xg` foundation metric (see [xg.md](xg.md)) is StatsBomb's own
pre-shot model: shot location, angle, body part — everything known *before*
the shot is struck. Post-shot xG (PSxG) is a different, harder question:
given where the shot actually ended up, the keeper's position, and the
traffic in front of goal, how save-able was it? PSxG is trained here, on
this warehouse's own data — StatsBomb's open release doesn't include one.

## Shots faced

Only shots that reached (or were heading into) the goal frame count as
"faced": `outcome in ('SAVED', 'GOAL')`. Blocked and off-target shots never
tested the keeper and are excluded. Shots that hit the post/bar are also
excluded — StatsBomb doesn't give them a clean end-location in the goal
frame the way saved/scored shots have, so the model has nothing to train
on for that case.

A keeper's shots faced = on-target shots by the opposing team across every
fixture they appear in (`appearance` table), ignoring goalkeeper
substitution timing — keepers are almost never subbed, so this is a
deliberate, low-cost Phase 0 simplification, not something the data
currently lets us verify shot-by-shot anyway.

## Model

A plain logistic regression (scaled features, `scikit-learn`), not
anything fancier — deliberately, given how few on-target shots one
competition-season provides. Features, matching the brief's named model
inputs:

- **shot location** → distance and angle to goal centre
- **body part** → header / other-body-part indicators (foot is the baseline)
- **on-target end location** → lateral offset from goal centre, and
  height (`end_z`, added to the schema specifically for this metric — see
  `engine/model/schema.py`)
- **freeze-frame keeper position and traffic** → keeper's lateral offset
  from the actual shot placement, keeper's depth off the line, and a count
  of non-keeper freeze-frame players standing between the shooter and
  goal within a 5-unit corridor of the direct line to goal centre (a
  simple geometric proxy for "traffic," not a physics-accurate blocking
  model — see `_traffic_count` in `engine/metrics/psxg.py`)

## Training set size and validation

Trained on **349 on-target shots** from the Bundesliga 2023/24 season
(Bayer Leverkusen's 34 matches, both sides), of which **109 were goals**
(31.2% conversion — expected, since "on target" already selects for
higher-quality attempts). Every StatsBomb open-data domestic-league
release is a single-club-season slice, so this is the full available
training set for Phase 0, not a subsample.

Validated by 5-fold stratified cross-validation (not a single train/test
split — the sample is too small for a held-out split to be stable):

- **Brier score: 0.089** (lower is better; a naive model always predicting
  the base rate would score `0.312 × 0.688 ≈ 0.215`, so the model is
  capturing real signal, not just the base rate)
- **Log loss: 0.298**

The final model is refit on all 349 shots (standard practice: cross-
validation estimates generalisation, it doesn't mean holding back data
from the deployed model).

## Caveats

- 349 shots is a small training set by the standards of a real PSxG model
  (published models are typically trained on tens of thousands of shots
  across many leagues/seasons). Treat psxg_ga as directionally informative
  for Phase 0, not a finished product — revisit once more competition-
  seasons are ingested.
- The traffic-count and keeper-offset features are simple geometric
  proxies, not validated against a physically-grounded blocking/positioning
  model.

## Bootstrap confidence interval

1000 resamples (with replacement) of a keeper's shots faced; `ci_low`/
`ci_high` are the 2.5th/97.5th percentiles of the resampled per-90 psxg_ga
values. Same underlying model each time — only which shots are counted
varies — so the interval reflects sampling variance in *which shots this
keeper happened to face*, not model uncertainty.
