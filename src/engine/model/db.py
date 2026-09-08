from pathlib import Path

import duckdb

from engine.model.schema import ensure_schema

DEFAULT_PATH = Path("warehouse/football.duckdb")


def connect(path: Path = DEFAULT_PATH) -> duckdb.DuckDBPyConnection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    ensure_schema(con)
    return con
