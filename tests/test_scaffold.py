"""Smoke test for the Phase 0 repo skeleton (build order step 1).

Not a metric test — there's no logic yet. This just fails loudly if the
`src/engine` layout or the pinned stack stops being importable.
"""

import importlib


def test_engine_subpackages_importable():
    for name in ("ingest", "model", "identity", "metrics", "benchmark", "render"):
        importlib.import_module(f"engine.{name}")


def test_pinned_stack_importable():
    for name in (
        "kloppy",
        "socceraction",
        "mplsoccer",
        "polars",
        "duckdb",
        "statsmodels",
        "sklearn",
        "jinja2",
        "xlsxwriter",
        "yaml",
    ):
        importlib.import_module(name)
