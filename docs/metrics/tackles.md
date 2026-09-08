# tackles

Count of `event.type = 'DUEL'` where `qualifiers.Duel` contains `GROUND` but
not `LOOSE_BALL` — tackle **attempts**, any outcome (won or lost). This is
attempt volume, not success rate; cross-reference against
[duels_won](duels_won.md) for that.

## Why "GROUND, not LOOSE_BALL" instead of a `TACKLE` value

kloppy's domain model has `DuelType.TACKLE`/`SLIDING_TACKLE` enum members,
but its StatsBomb adapter never emits them for this provider — a raw
StatsBomb "Tackle" duel is mapped to `DuelQualifier(value=DuelType.GROUND)`
instead. `qualifiers.Duel = ["TACKLE"]`/`["SLIDING_TACKLE"]` can never
appear in this warehouse; a filter written against those values silently
returns zero forever, for every player, with no suppression warning (the
original Phase 0 bug this doc used to describe).

`GROUND` alone isn't unique to tackles, though: a StatsBomb 50/50 event
(a contest for a loose ball, not a tackle on an opponent in possession) is
mapped to *two* Duel qualifiers, `[LOOSE_BALL, GROUND]`. Excluding
`LOOSE_BALL` is what separates a genuine tackle attempt from a 50/50.
Qualifier values are stored as JSON arrays per key precisely so this
distinction survives ingest — see `qualifier_contains` in
`engine.metrics.foundation` and `_serialize_qualifiers` in
`engine.ingest.statsbomb`.

See [foundation_adjustments.md](foundation_adjustments.md) for `per_90`,
`possession`, and `opposition_strength`.
