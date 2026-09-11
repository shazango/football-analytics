# progressive_carries

A carry that moves the ball meaningfully closer to the opponent's goal.
Counted per 90 (`adjustments: [per_90, possession, opposition_strength]`,
`min_sample: 450` minutes).

This metric shared
[progressive_passes.md](progressive_passes.md) until now. The progression
threshold is genuinely the same rule and is documented once, below; what
that page could not say is what separates a carry from a pass, which is
most of what a reader wants to know when the two appear on the same
report with different numbers.

## Detection

The event is `type = 'CARRY'` and satisfies the shared progression test:
it either moves the ball at least **25% of the remaining distance** to
the opponent's byline in our normalised 0-100 coordinates, or ends inside
the opponent's penalty box (`x >= 85`, `22.5 <= y <= 77.5`).

Both conditions are the ones in
[progressive_passes.md](progressive_passes.md), evaluated against the
same `_PROGRESSIVE_SQL` predicate in `engine/metrics/foundation.py` — one
implementation, so the two metrics cannot drift apart on what
"progressive" means.

## How this differs from progressive_passes

**No completion filter.** A pass has an outcome and an incomplete one
never qualifies, because the ball did not actually arrive. A carry has no
equivalent outcome in StatsBomb's model: the player had the ball and
moved with it. So every qualifying carry counts, and a carry that ends in
a tackle still counts for the ground it covered before the tackle.

That asymmetry is worth holding in mind when reading the two side by
side. Progressive passes are a record of successful progression;
progressive carries are a record of attempted progression that covered
ground. A high carry count is not evidence that the possession survived.

**Different players do it.** Carrying is concentrated in wide and
attacking roles in a way passing is not. On the Bundesliga 2023/24 slice
Wirtz leads Leverkusen midfielders at 9.51 per 90 against a positional
median of 3.85, while Xhaka — the squad's clear leader in progressive
passes at 14.1 per 90 — sits at 2.00. Treating the two as one number
would lose exactly the distinction a scout is looking for.

## Known limits

Carry events are provider-derived rather than observed: StatsBomb infers
a carry from the gap between where a player receives the ball and where
their next action happens. Short or cluttered sequences can produce
carries that a viewer would not describe as a run with the ball. The 25%
threshold filters most of these out by construction, but the metric
inherits whatever the provider's carry detection does.

See [foundation_adjustments.md](foundation_adjustments.md) for `per_90`,
`possession` and `opposition_strength`.
