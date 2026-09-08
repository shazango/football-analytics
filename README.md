# football-analytics

Analytics engine for football clubs and agents below the elite tier: derived
metrics and reporting on open data (StatsBomb events/360, SkillCorner
tracking). See [PHASE-0-BRIEF.md](PHASE-0-BRIEF.md) for the full spec this
repo is being built against.

Everything here runs on free, open data — no premium feeds, no
paid APIs. Attribution to StatsBomb is required in any rendered output
(see [THIRD_PARTY_LICENCES.md](THIRD_PARTY_LICENCES.md)).

## Setup

```
make install   # uv sync
make test      # uv run pytest
```

## Ingest

Downloads StatsBomb open data (cached under `data/`, gitignored) and loads
it into a DuckDB warehouse (`warehouse/football.duckdb`, gitignored) under
the canonical schema in `src/engine/model/schema.py`.

```
make ingest    # defaults to Bundesliga 2023/24 (Bayer Leverkusen) —
               # the only open-data slice with both a full single-club
               # season and 100% 360 (freeze-frame) coverage
```

Override with `make ingest COMPETITION=<id> SEASON=<id>` (ids per
StatsBomb's `competitions.json`).

## Layout

```
src/engine/
  ingest/      # source loaders (StatsBomb via kloppy; SkillCorner later)
  model/       # canonical DuckDB schema
  identity/    # deterministic alias resolution across data sources
  metrics/     # metric definition loader/runtime + implementations
  render/      # PDF / XLSX / JSON report renderers (not yet built)
metrics/       # metric definitions, as YAML (one file per metric)
docs/metrics/  # methodology page per metric (required before a metric "counts as done")
tests/
  fixtures/    # a small committed slice of open data, used instead of live downloads
```

## Status

Following the brief's build order (§11). Current progress:

- [x] 1. Repo skeleton, `uv`, Makefile, licences file
- [x] 2. StatsBomb ingest via kloppy into DuckDB; canonical schema
- [x] 3. Derive `game_state` and `possession_id` during ingest
- [x] 4. Deterministic identity resolution
- [x] 5. Metric definition loader and runtime, with versioning and input hashing
- [x] 6. Foundation layer plus the three adjustments
- [x] 7. Benchmark sets
- [ ] 8. `psxg_ga` with confidence bands and defensive context
- [ ] 9. `throw_in_profile`
- [ ] 10. `supply_attribution`
- [ ] 11. `line_break_value`, validated against Impect open data
- [ ] 12. `game_state_response`
- [ ] 13. Renderers: JSON, then XLSX, then PDF
- [ ] 14. SkillCorner ingest into `physical_sample`
