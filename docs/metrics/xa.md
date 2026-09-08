# xa

Sum, across a player's shot-assist passes, of the xG value of the shot
each pass created. Not a kloppy-native field: StatsBomb links a
shot-assist pass to the shot it produced via an id reference
(`assisted_shot_id` / `key_pass_id`), which we resolve once at ingest and
store as the pass's own `qualifiers.xA` value — the id reference itself is
never persisted (PHASE-0-BRIEF.md §12: derived values only). See
`_serialize_qualifiers` in `engine/ingest/statsbomb.py`.

See [foundation_adjustments.md](foundation_adjustments.md) for `per_90`,
`possession`, and `opposition_strength`.
