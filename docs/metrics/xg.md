# xg

Sum of StatsBomb's own shot-level xG value (`event.qualifiers.xG`, taken
directly from kloppy's parsed `ExpectedGoals` statistic — we don't retrain
an xG model in Phase 0) across all shots attributed to the player. Own
goals carry no xG value in StatsBomb's data, so they don't contribute.

See [foundation_adjustments.md](foundation_adjustments.md) for `per_90`,
`possession`, and `opposition_strength`.
