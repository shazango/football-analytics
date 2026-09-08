# shots

Count of `event.type = 'SHOT'` attributed to the player, across the
competition-season. Excludes own goals — StatsBomb attributes those to the
scorer as a shot event, but an own goal isn't a shot the player took.
Blocked/off-target/saved/goal outcomes all count equally — this is shot
*volume*, not quality; see [xg](xg.md) for that.

See [foundation_adjustments.md](foundation_adjustments.md) for `per_90`,
`possession`, and `opposition_strength`.
