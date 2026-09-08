"""JSON renderer (build order step 13). Pure projection of the report IR
— "same projection plus definition ids and versions" (brief §9), i.e. the
full IR, unsuppressed, since definition_id/version/min_sample are already
part of every metric entry `build_report` produces.
"""

import json
from pathlib import Path


def render_json(report: dict, path: Path) -> None:
    path.write_text(json.dumps(report, indent=2, default=str))
