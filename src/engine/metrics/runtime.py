"""Compute-and-store pipeline for metrics (build order step 5).

`metric_value` (schema.py) is an append-only ledger, not an upsert table —
no primary key, `computed_at` distinguishes repeat computations. Consumers
select the latest `computed_at` per (person_id, fixture_id, definition_id,
definition_version) when they want "the current value".

Suppressing sub-`min_sample` values is a *rendering* concern (build order
step 13): this layer always stores what was actually computed, per brief
§6 ("write the row but suppress the value from reports").
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from engine.metrics.definitions import MetricDefinition
from engine.metrics.registry import get_implementation


@dataclass
class MetricResult:
    value: float | None
    sample_size: int
    ci_low: float | None = None
    ci_high: float | None = None


def compute_input_hash(definition: MetricDefinition, **params) -> str:
    payload = {
        "definition_id": definition.id,
        "definition_version": definition.version,
        **params,
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def compute_and_store(
    con,
    definition: MetricDefinition,
    person_id: int,
    competition_id: str,
    season: str,
    fixture_id: int | None = None,
    adjustment: str | None = None,
    game_state_bucket: str | None = None,
    **params,
) -> MetricResult:
    impl = get_implementation(definition.id)
    result = impl(
        con,
        definition=definition,
        person_id=person_id,
        competition_id=competition_id,
        season=season,
        fixture_id=fixture_id,
        adjustment=adjustment,
        game_state_bucket=game_state_bucket,
        **params,
    )

    if definition.confidence == "bootstrap" and (
        result.ci_low is None or result.ci_high is None
    ):
        # Brief §6: "Never render a bare point estimate for these." Caught
        # here, at write time, not later in a renderer that's too far from
        # the implementation to know it forgot.
        raise ValueError(
            f"metric '{definition.id}' declares confidence: bootstrap but "
            "its implementation returned no confidence interval"
        )

    input_hash = compute_input_hash(
        definition,
        person_id=person_id,
        competition_id=competition_id,
        season=season,
        fixture_id=fixture_id,
        adjustment=adjustment,
        game_state_bucket=game_state_bucket,
        **params,
    )

    con.execute(
        "INSERT INTO metric_value VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            person_id,
            fixture_id,
            competition_id,
            season,
            definition.id,
            definition.version,
            adjustment,
            game_state_bucket,
            result.value,
            result.sample_size,
            result.ci_low,
            result.ci_high,
            datetime.now(timezone.utc),
            input_hash,
        ],
    )
    return result
