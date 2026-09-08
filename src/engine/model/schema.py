"""Canonical DuckDB schema (PHASE-0-BRIEF.md §5).

Built on kloppy's event model rather than a parallel one: kloppy parses and
normalises provider data in memory, this schema is just where the parsed
result is persisted. Coordinates are 0-100 (kloppy's "opta" coordinate
system). Orientation is ACTION_EXECUTING_TEAM: for every event, x increases
toward the goal the acting team is attacking, regardless of home/away — so
"progressive" and "line-breaking" metrics don't need to flip based on which
team or which half.

`possession_id` is StatsBomb's own chain number namespaced by fixture_id
(fixture_id * 10_000 + raw possession number); `game_state` is the score
margin for the event's own team as of just before the event, e.g. "1",
"0", "-2". Both derived during ingest — see engine.ingest.statsbomb.
"""

DDL = """
CREATE TABLE IF NOT EXISTS competition (
    id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    country VARCHAR,
    tier VARCHAR,
    gender VARCHAR,
    season VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS team (
    id BIGINT PRIMARY KEY,
    name VARCHAR NOT NULL,
    competition_id VARCHAR NOT NULL REFERENCES competition(id)
);

CREATE TABLE IF NOT EXISTS person (
    id BIGINT PRIMARY KEY,
    canonical_name VARCHAR NOT NULL,
    dob DATE,
    foot VARCHAR,
    primary_position VARCHAR
);

CREATE TABLE IF NOT EXISTS fixture (
    id BIGINT PRIMARY KEY,
    competition_id VARCHAR NOT NULL REFERENCES competition(id),
    home_team_id BIGINT NOT NULL REFERENCES team(id),
    away_team_id BIGINT NOT NULL REFERENCES team(id),
    kickoff_utc TIMESTAMP
);

CREATE TABLE IF NOT EXISTS appearance (
    fixture_id BIGINT NOT NULL REFERENCES fixture(id),
    person_id BIGINT NOT NULL REFERENCES person(id),
    team_id BIGINT NOT NULL REFERENCES team(id),
    minutes DOUBLE NOT NULL,
    start_min DOUBLE NOT NULL,
    end_min DOUBLE NOT NULL,
    PRIMARY KEY (fixture_id, person_id)
);

CREATE TABLE IF NOT EXISTS event (
    fixture_id BIGINT NOT NULL REFERENCES fixture(id),
    sequence BIGINT NOT NULL,
    timestamp_ms BIGINT NOT NULL,
    period INTEGER NOT NULL,
    type VARCHAR NOT NULL,
    actor_person_id BIGINT REFERENCES person(id),
    team_id BIGINT REFERENCES team(id),
    location_x DOUBLE,
    location_y DOUBLE,
    end_x DOUBLE,
    end_y DOUBLE,
    end_z DOUBLE,  -- shot height in the goal frame; NULL for every other event type
    outcome VARCHAR,
    possession_id BIGINT,
    qualifiers JSON,
    game_state VARCHAR,
    freeze_frame JSON,
    PRIMARY KEY (fixture_id, sequence)
);

CREATE TABLE IF NOT EXISTS physical_sample (
    fixture_id BIGINT NOT NULL REFERENCES fixture(id),
    person_id BIGINT NOT NULL REFERENCES person(id),
    bucket_start_min DOUBLE NOT NULL,
    bucket_end_min DOUBLE NOT NULL,
    distance_m DOUBLE,
    hi_distance_m DOUBLE,
    sprint_count INTEGER,
    accel_count INTEGER,
    decel_count INTEGER,
    max_speed_ms DOUBLE,
    source VARCHAR NOT NULL,
    PRIMARY KEY (fixture_id, person_id, bucket_start_min, source)
);

CREATE TABLE IF NOT EXISTS person_alias (
    person_id BIGINT NOT NULL REFERENCES person(id),
    source VARCHAR NOT NULL,
    source_ref VARCHAR NOT NULL,
    display_name VARCHAR NOT NULL,
    confidence DOUBLE NOT NULL,
    confirmed_by VARCHAR,
    PRIMARY KEY (source, source_ref)
);

-- Deterministic identity resolution (§5) parks anything ambiguous here
-- instead of guessing. Populated starting build order step 4.
CREATE TABLE IF NOT EXISTS unresolved_alias (
    source VARCHAR NOT NULL,
    source_ref VARCHAR NOT NULL,
    display_name VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    detected_at TIMESTAMP NOT NULL,
    PRIMARY KEY (source, source_ref)
);

CREATE TABLE IF NOT EXISTS metric_value (
    person_id BIGINT NOT NULL REFERENCES person(id),
    fixture_id BIGINT REFERENCES fixture(id),
    competition_id VARCHAR NOT NULL REFERENCES competition(id),
    season VARCHAR NOT NULL,
    definition_id VARCHAR NOT NULL,
    definition_version INTEGER NOT NULL,
    -- Not in the brief's literal §5 schema, added in step 6: adjustment is a
    -- *runtime-switchable* choice (raw/per_90/possession/opposition_strength),
    -- so a value on its own doesn't say which one produced it. NULL for
    -- ratio metrics (e.g. pass_completion_*_third), which have none.
    adjustment VARCHAR,
    -- Added in step 12, same reasoning as `adjustment` above: a foundation
    -- stat can be re-scoped to a game-state window (leading/level/trailing/
    -- trailing_2plus/after_conceding_10min); NULL means the whole-season
    -- aggregate, as every metric before step 12 already stored.
    game_state_bucket VARCHAR,
    value DOUBLE,
    sample_size INTEGER NOT NULL,
    ci_low DOUBLE,
    ci_high DOUBLE,
    computed_at TIMESTAMP NOT NULL,
    input_hash VARCHAR NOT NULL
);

-- Distributions of a foundation metric across all qualifying players in one
-- competition/season/position-bucket (build order step 7). Append-only, like
-- metric_value: `computed_at` breaks ties for "the current benchmark".
CREATE TABLE IF NOT EXISTS benchmark_distribution (
    competition_id VARCHAR NOT NULL REFERENCES competition(id),
    season VARCHAR NOT NULL,
    position_bucket VARCHAR NOT NULL,
    definition_id VARCHAR NOT NULL,
    definition_version INTEGER NOT NULL,
    adjustment VARCHAR,
    n INTEGER NOT NULL,
    sample_values JSON NOT NULL,
    computed_at TIMESTAMP NOT NULL
);
"""


def ensure_schema(con) -> None:
    con.execute(DDL)
