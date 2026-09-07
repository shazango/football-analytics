# Phase 0 Build Brief

Standalone brief for an agentic coding session. Everything here runs on free,
openly licensed data. No API keys, no credentials, no third-party accounts.

**Goal of Phase 0:** produce one Player Report, for one real player, from open
data, rendered to PDF, XLSX and JSON, driven by versioned metric definitions.

**Definition of done:** `make report PLAYER=<id>` writes three files to
`out/`, every number in them traceable to a metric definition with a version,
and the full metric test suite passes.

---

## 1. Context

We are building an analytics engine for football clubs and agents below the
elite tier. The product is derived metrics plus reporting, not data collection.

Phase 0 proves the engine on open data. Later phases add licensed connectors,
but nothing in Phase 0 depends on them.

**Non-goals for Phase 0.** No web UI beyond a trivial trigger. No auth, no
users, no multi-tenancy. No live data. No paid connectors. No deployment.
Do not build these even if they seem natural next steps.

---

## 2. Data sources

Both are free and openly licensed. Do not add any other source.

### StatsBomb Open Data
- Repo: `https://github.com/hudl/open-data`
- Events, lineups, matches, competitions, and `three-sixty` freeze frames
- Licence: free for research and public analytics work; attribution to
  StatsBomb required in any published output
- The 360 freeze frames are essential — they give visible player positions at
  the moment of each event. Check which competitions actually have them before
  choosing a demo player.

### SkillCorner Open Data
- Repo: `https://github.com/SkillCorner/opendata`
- 10 matches of A-League 2024/25 broadcast tracking at 10fps, plus physical
  aggregates
- Licence: MIT
- Use for the physical stream and for validating the tracking-based metrics

Add a `THIRD_PARTY_LICENCES.md` at the repo root recording both, plus the
library licences in §3.

---

## 3. Stack

Python 3.12. Use these; do not substitute.

| Purpose | Library | Licence |
|---|---|---|
| Provider normalisation | `kloppy` | BSD-3 |
| Possession value (xT, VAEP), SPADL | `socceraction` | MIT |
| Pitch plots, radars | `mplsoccer` | MIT |
| Dataframes | `polars` (convert to `pandas` at library boundaries) | |
| Local analytical store | `duckdb` | |
| Stats / bootstrapping | `statsmodels`, `scikit-learn` | |
| Templating | `jinja2` | |
| PDF | `weasyprint` | |
| XLSX | `xlsxwriter` | |
| Packaging | `uv` | |
| Tests | `pytest` | |

**Important:** kloppy already handles provider schemas and pitch coordinate
normalisation. Do not write a custom event parser. socceraction already
implements xT and VAEP. Do not reimplement possession value.

BSD-3 note: do not use kloppy's or its contributors' names in any promotional
copy.

---

## 4. Repository layout

```
.
├── pyproject.toml
├── Makefile
├── THIRD_PARTY_LICENCES.md
├── data/                     # gitignored; raw open data lands here
├── warehouse/                # gitignored; duckdb file
├── out/                      # gitignored; generated reports
├── docs/
│   └── metrics/              # one markdown methodology page per metric
├── metrics/                  # YAML metric definitions (see §6)
├── src/engine/
│   ├── ingest/               # source loaders
│   ├── model/                # canonical schema + duckdb DDL
│   ├── identity/             # alias resolution
│   ├── metrics/              # metric runtime + implementations
│   ├── benchmark/            # reference distributions
│   └── render/               # pdf / xlsx / json renderers
└── tests/
    ├── fixtures/             # committed slice of open data
    └── metrics/              # one test module per metric
```

---

## 5. Canonical data model

Build on kloppy's model rather than inventing a parallel one. Persist to DuckDB
with these tables.

```sql
competition(id, name, country, tier, gender, season)
team(id, name, competition_id)
person(id, canonical_name, dob, foot, primary_position)
fixture(id, competition_id, home_team_id, away_team_id, kickoff_utc)
appearance(fixture_id, person_id, team_id, minutes, start_min, end_min)

event(
  fixture_id, sequence, timestamp_ms, period,
  type,                  -- pass | shot | carry | pressure | duel | throw_in | ...
  actor_person_id, team_id,
  location_x, location_y,      -- normalised 0-100
  end_x, end_y,
  outcome,
  possession_id,
  qualifiers JSON,
  game_state,                  -- derived: score margin at event time
  freeze_frame JSON            -- nullable; 360 positions
)

physical_sample(
  fixture_id, person_id, bucket_start_min, bucket_end_min,
  distance_m, hi_distance_m, sprint_count, accel_count, decel_count,
  max_speed_ms, source
)

person_alias(person_id, source, source_ref, display_name, confidence, confirmed_by)

metric_value(
  person_id, fixture_id NULL, competition_id, season,
  definition_id, definition_version,
  value, sample_size, ci_low NULL, ci_high NULL,
  computed_at, input_hash
)
```

Notes:
- Normalise all pitch coordinates to 0–100 at ingest. kloppy does this; make
  sure the orientation is consistent and document which way is "attacking".
- `game_state` is derived during ingest, not stored upstream. Compute score
  margin at each event timestamp and attach it. Several metrics depend on it.
- `possession_id` groups events into chains. Needed for supply attribution.

### Identity resolution
Deterministic only in Phase 0. Match on exact name plus date of birth, or on a
shared provider ID where kloppy surfaces one. Anything ambiguous goes to a
`unresolved_aliases` table and is reported at the end of the run. Do **not**
build fuzzy matching or a confirmation UI yet.

---

## 6. Metric definitions as data

Every metric is a YAML file in `metrics/`, loaded at runtime. The Python
implementation is registered against the definition id.

```yaml
id: psxg_ga
version: 1
title: Post-shot expected goals minus goals allowed
applies_to: goalkeeper
requires:
  - shot.location
  - shot.end_location
  - shot.body_part
  - freeze_frame
min_sample: 40            # shots faced
adjustments: [per_90]
confidence: bootstrap
methodology: docs/metrics/psxg_ga.md
```

Rules the runtime must enforce:
- Every value written to `metric_value` carries `definition_id`,
  `definition_version`, `computed_at` and `input_hash`.
- If sample size is below `min_sample`, write the row but suppress the value
  from reports, showing "insufficient sample" instead.
- If `confidence: bootstrap`, compute and store a confidence interval. Never
  render a bare point estimate for these.
- Each metric has a methodology page in `docs/metrics/`. The report links to it.
  This is our substitute for being an official data provider.

---

## 7. Metrics to implement, in order

### 7.1 Foundation layer
Per-90 and possession-adjusted versions of: shots, xG, xA, key passes,
progressive passes, progressive carries, duels won, tackles, interceptions,
recoveries, aerials, pass completion by third.

Adjustments:
- Per-90 with a configurable minutes threshold (default 450)
- Possession adjustment — the field genuinely disagrees on the formula, so make
  ours explicit, documented and switchable rather than picking one silently
- Opposition strength adjustment — weight each match by opponent quality.
  Materially changes lower-league numbers and almost nobody does it.

### 7.2 `psxg_ga` — the wedge metric
Post-shot expected goals minus goals allowed, for goalkeepers.

Model inputs: shot location, body part, on-target end location, and freeze-frame
keeper position and traffic between shooter and goal.

Output: goals prevented above expectation, per 90 and cumulative, **with
confidence bands**. Shot-stopping is high variance; a point estimate is
misleading.

Also compute the defensive context, which is a separate thing from the keeper's
own quality: mean xG per shot faced, share of shots from central zones, share
unpressured. This is deliberately the "a keeper is only as good as his defence"
decomposition.

Train the post-shot model on the open data. Document the training set size and
validation approach in the methodology page.

### 7.3 `throw_in_profile` — the second wedge
Throw-ins are logged by every provider and derived by none. Roughly 35–60 per
match.

Three components:
- **Fast** — time from ball out of play to throw taken; retention rate when taken quickly
- **Long** — throw distance, territory gained, aerial duel outcome at landing zone
- **Clever** — whether the throw or first receiver breaks a defensive line
  (reuse `line_break_value`, §7.5)

Headline output: **retention under pressure** — share of throw-ins retained when
the throwing team is pressed, benchmarked by league and pitch third.

Also compute the defensive mirror: opposition throw-in retention allowed.

### 7.4 `supply_attribution`
Decompose xG received by which teammate created it, using possession chains.
Report concentration: share from top supplier, and a Herfindahl index across
suppliers.

This is the "a striker is only as good as his supply" measure and it is the
first component of system dependency. Do not attempt with-or-without-you
analysis in Phase 0 — the sample is far too thin.

### 7.5 `line_break_value`
Weight a progressive pass by how many opposition players it removes from the
play, using the freeze frame, weighted by their position relative to goal.

Validate against the Impect open dataset (Bundesliga 2023/24, loadable via
kloppy) which carries packing and packing-xG as a reference implementation.

### 7.6 `game_state_response`
Split foundation metrics by match state: leading, level, trailing by margin, and
by time bucket. Headline cuts: output in the 10 minutes after conceding, and
pressing intensity when 2+ goals down.

**Naming discipline:** this is a game-state response profile. It is never
labelled as a psychological attribute of an individual. Do not use the word
"morale" anywhere in code, output or documentation.

---

## 8. Benchmark sets

For a given competition, season and position bucket, compute the full
distribution of every foundation metric across all qualifying players.

Store the distribution, not just percentiles, so reports can show where a player
sits within it.

This is the recurring job clubs currently do by hand in spreadsheets, and it is
the substrate the Player Report reads from. Treat it as first-class, not as a
helper for the report.

---

## 9. The Player Report

One player, one competition, one season. Three renderers off a single
intermediate representation — renderers must not recompute anything.

Contents:
1. Identity block — age, position, minutes, league
2. **Contextualised foundation metrics** — never a bare number. Every stat shown
   against its positional and league distribution, with a distribution plot
3. Position-specific panel — `psxg_ga` and defensive context for goalkeepers;
   `supply_attribution` for forwards; `throw_in_profile` where relevant
4. Game-state response summary
5. Methodology links and a StatsBomb attribution line

Output formats:
- **PDF** via Jinja2 → WeasyPrint. Board-ready. Aim for one page of substance
  with detail underneath, not three pages of everything.
- **XLSX** via xlsxwriter. Flat tabular projection. This is the working format
  for the actual users.
- **JSON**. Same projection plus definition ids and versions.

---

## 10. Testing

This matters more than usual, because a silently wrong metric looks fine.

- Commit a small fixed slice of open data to `tests/fixtures/`
- One test module per metric, with hand-checked expected values
- **Regression tests on metric output** — if a definition changes, the test
  fails and the version must be bumped. This is the guard on reproducibility.
- Test that sub-`min_sample` values are suppressed in rendered output
- Test that renderers produce identical numbers across all three formats

---

## 11. Build order

1. Repo skeleton, `uv`, Makefile, licences file
2. Ingest StatsBomb open data via kloppy into DuckDB; canonical schema
3. Derive `game_state` and `possession_id` during ingest
4. Deterministic identity resolution
5. Metric definition loader and runtime, with versioning and input hashing
6. Foundation layer plus the three adjustments
7. Benchmark sets
8. `psxg_ga` with confidence bands and defensive context
9. `throw_in_profile`
10. `supply_attribution`
11. `line_break_value`, validated against Impect open data
12. `game_state_response`
13. Renderers: JSON, then XLSX, then PDF
14. SkillCorner ingest into `physical_sample` (last; not needed for the report)

Stop at 14. Do not start on connectors, auth, or a web app.

---

## 12. Constraints to respect

- **No premium data anywhere in this phase.** Everything is open data.
- **Never persist raw third-party payloads** — the architecture in later phases
  depends on this, so establish the habit now: parse, compute, store derived
  values only.
- **Every metric needs a methodology page** before it counts as done.
- **No point estimates for high-variance metrics.** Confidence intervals or
  nothing.
- Attribution to StatsBomb in any rendered output.
