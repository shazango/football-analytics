"""Step 5: metric definition loader and compute/store runtime."""

from pathlib import Path

import duckdb
import pytest

from engine.metrics import registry
from engine.metrics.definitions import load_definition
from engine.metrics.runtime import MetricResult, compute_and_store, compute_input_hash
from engine.model.schema import ensure_schema

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "metrics"


@pytest.fixture
def con():
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    con.execute("insert into competition values ('9-281', 'Bundesliga', 'Germany', NULL, 'male', '2023/2024')")
    con.execute("insert into person values (1, 'Test Player', NULL, NULL, 'Midfielder')")
    return con


@pytest.fixture
def definition():
    return load_definition(FIXTURE_DIR / "dummy_metric.yaml")


@pytest.fixture(autouse=True)
def clean_registry():
    # Registry is a module-level dict; don't leak test registrations.
    yield
    registry._REGISTRY.pop("dummy_metric", None)


def test_load_definition_parses_fields_and_defaults(definition):
    assert definition.id == "dummy_metric"
    assert definition.version == 1
    assert definition.min_sample == 10
    assert definition.confidence == "bootstrap"
    assert definition.requires == ["nothing"]
    assert definition.adjustments == []


def test_load_definition_rejects_missing_methodology_page(tmp_path):
    bad = tmp_path / "bad_metric.yaml"
    bad.write_text(
        "id: bad_metric\nversion: 1\ntitle: Bad\napplies_to: all\n"
        "min_sample: 1\nmethodology: does/not/exist.md\n"
    )
    with pytest.raises(FileNotFoundError):
        load_definition(bad)


def test_registry_round_trip():
    @registry.register("dummy_metric")
    def impl(con, **kwargs):
        return MetricResult(value=1.0, sample_size=5)

    assert registry.get_implementation("dummy_metric") is impl


def test_registry_missing_implementation_raises():
    with pytest.raises(KeyError):
        registry.get_implementation("never_registered")


def test_compute_and_store_happy_path(con, definition):
    @registry.register("dummy_metric")
    def impl(con, **kwargs):
        return MetricResult(value=2.5, sample_size=50, ci_low=2.0, ci_high=3.0)

    result = compute_and_store(
        con, definition, person_id=1, competition_id="9-281", season="2023/2024"
    )
    assert result.value == 2.5

    row = con.execute(
        "select person_id, definition_id, definition_version, value, sample_size, "
        "ci_low, ci_high, input_hash from metric_value"
    ).fetchone()
    assert row[:7] == (1, "dummy_metric", 1, 2.5, 50, 2.0, 3.0)
    assert row[7]  # input_hash present


def test_bootstrap_metric_without_ci_raises(con, definition):
    @registry.register("dummy_metric")
    def impl(con, **kwargs):
        return MetricResult(value=2.5, sample_size=50)  # no CI

    with pytest.raises(ValueError, match="bootstrap"):
        compute_and_store(
            con, definition, person_id=1, competition_id="9-281", season="2023/2024"
        )


def test_sub_min_sample_value_is_still_stored(con, definition):
    # Suppression from reports happens at render time, not here.
    @registry.register("dummy_metric")
    def impl(con, **kwargs):
        return MetricResult(value=9.9, sample_size=3, ci_low=1.0, ci_high=2.0)

    compute_and_store(
        con, definition, person_id=1, competition_id="9-281", season="2023/2024"
    )
    value, sample_size = con.execute(
        "select value, sample_size from metric_value"
    ).fetchone()
    assert value == 9.9
    assert sample_size == 3 < definition.min_sample


def test_input_hash_is_deterministic_and_param_sensitive(definition):
    h1 = compute_input_hash(definition, person_id=1, competition_id="9-281", season="2023/2024")
    h2 = compute_input_hash(definition, person_id=1, competition_id="9-281", season="2023/2024")
    h3 = compute_input_hash(definition, person_id=2, competition_id="9-281", season="2023/2024")
    assert h1 == h2
    assert h1 != h3
