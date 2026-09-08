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
