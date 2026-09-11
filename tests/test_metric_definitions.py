"""Rules every metric definition has to satisfy (PHASE-0-BRIEF.md §6, §12).

These are catalogue-level invariants, not per-metric behaviour: the things
that go wrong when a new YAML is added by copying an old one.
"""

import pytest

from engine.metrics.definitions import load_all
from engine.render.format import UNIT_SUFFIX

# Methodology pages that deliberately document several metrics at once,
# because the metrics are one idea measured in several places and
# splitting the page would mean three copies of the same explanation.
# Anything not listed here must have a page of its own: progressive_carries
# pointed at progressive_passes.md and so a reader following the link was
# told about passes.
SHARED_METHODOLOGY_PAGES = {
    "docs/metrics/pass_completion_by_third.md": {
        "pass_completion_defensive_third",
        "pass_completion_middle_third",
        "pass_completion_attacking_third",
    },
    "docs/metrics/defensive_context.md": {
        "defensive_xg_per_shot_faced",
        "defensive_shots_central_share",
        "defensive_shots_unpressured_share",
    },
    "docs/metrics/throw_in_profile.md": {
        "throw_in_retention_under_pressure",
        "throw_in_retention_rate",
        "throw_in_distance",
        "throw_in_territory_gained",
        "throw_in_aerial_win_rate",
        "throw_in_clever_share",
        "throw_in_retention_allowed",
    },
    "docs/metrics/supply_attribution.md": {
        "supply_assisted_xg_share",
        "supply_top_supplier_share",
        "supply_herfindahl_index",
    },
}


@pytest.fixture(scope="module")
def definitions():
    return load_all()


def test_no_two_metrics_share_a_methodology_page_unless_recorded(definitions):
    by_page: dict[str, set[str]] = {}
    for definition in definitions.values():
        by_page.setdefault(definition.methodology, set()).add(definition.id)

    for page, ids in sorted(by_page.items()):
        if len(ids) == 1:
            continue
        assert page in SHARED_METHODOLOGY_PAGES, (
            f"{sorted(ids)} share '{page}' but it is not recorded as a shared "
            "page — give the metric its own page, or add it here with a reason"
        )
        assert ids == SHARED_METHODOLOGY_PAGES[page], (
            f"'{page}' is recorded as covering "
            f"{sorted(SHARED_METHODOLOGY_PAGES[page])} but is used by {sorted(ids)}"
        )


def test_every_recorded_shared_page_is_still_shared(definitions):
    # Keeps the list above from rotting into a set of stale exemptions.
    for page, ids in SHARED_METHODOLOGY_PAGES.items():
        actual = {d.id for d in definitions.values() if d.methodology == page}
        assert actual == ids, f"'{page}' is recorded for {sorted(ids)}, found {sorted(actual)}"


def test_declared_units_are_known(definitions):
    for definition in definitions.values():
        assert definition.unit in UNIT_SUFFIX, (
            f"metric '{definition.id}' declares unknown unit '{definition.unit}'"
        )


def test_percentage_metrics_are_declared_as_such(definitions):
    # A value on a 0-100 scale that doesn't say it's a percentage renders as
    # a bare "80.0" beside a summary that says "80%".
    for definition in definitions.values():
        if definition.id.endswith(("_share", "_rate")) or "pass_completion" in definition.id:
            assert definition.unit == "percent", (
                f"metric '{definition.id}' looks like a percentage but declares "
                f"unit={definition.unit!r}"
            )
