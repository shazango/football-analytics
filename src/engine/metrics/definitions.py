"""Load metric definitions as data (PHASE-0-BRIEF.md §6).

A metric is a YAML file in `metrics/` (repo root); the Python
implementation is registered separately against its `id` (see registry.py).
Definitions are loaded fresh each time — there are only ever a handful of
these, no need to cache.
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_DEFINITIONS_DIR = Path("metrics")


@dataclass(frozen=True)
class MetricDefinition:
    id: str
    version: int
    title: str
    applies_to: str
    min_sample: int
    methodology: str
    requires: list[str] = field(default_factory=list)
    adjustments: list[str] = field(default_factory=list)
    confidence: str = "point"  # "point" | "bootstrap"


def load_definition(path: Path) -> MetricDefinition:
    raw = yaml.safe_load(path.read_text())
    methodology = raw["methodology"]
    if not Path(methodology).exists():
        # Brief §12: "every metric needs a methodology page before it counts
        # as done" — enforced here, not left as a doc-review afterthought.
        raise FileNotFoundError(
            f"metric '{raw['id']}' declares methodology page '{methodology}' "
            "which does not exist"
        )
    return MetricDefinition(
        id=raw["id"],
        version=raw["version"],
        title=raw["title"],
        applies_to=raw["applies_to"],
        min_sample=raw["min_sample"],
        methodology=methodology,
        requires=raw.get("requires", []),
        adjustments=raw.get("adjustments", []),
        confidence=raw.get("confidence", "point"),
    )


def load_all(directory: Path = DEFAULT_DEFINITIONS_DIR) -> dict[str, MetricDefinition]:
    return {d.id: d for d in (load_definition(p) for p in sorted(directory.glob("*.yaml")))}
