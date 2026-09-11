# progressive_passes

Carries have their own page:
[progressive_carries.md](progressive_carries.md). The progression
threshold below is shared by both and implemented once.

No single formula for "progressive" is standard across the industry —
published definitions vary in threshold and units. Ours, explicit and
fixed for Phase 0:

A completed pass (or any carry) qualifies if it either:
- moves the ball at least **25% of the remaining distance** to the
  opponent's byline, measured in our normalised 0-100 pitch coordinates
  (`x` increases toward the attacking goal regardless of team/half — see
  `engine/model/schema.py`), **or**
- ends inside the opponent's **penalty box** (`x >= 85`,
  `22.5 <= y <= 77.5`, derived from a 120x80y pitch normalised to 0-100).

Incomplete passes never qualify (the ball didn't actually get there).
Carries have no equivalent "completion" outcome in our data, so none are
excluded on that basis.

See [foundation_adjustments.md](foundation_adjustments.md) for `per_90`,
`possession`, and `opposition_strength`.
