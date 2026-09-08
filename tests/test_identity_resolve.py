"""Step 4: deterministic identity resolution (no fuzzy matching)."""

from datetime import date

import duckdb
import pytest

from engine.identity.resolve import report_unresolved, resolve_person
from engine.model.schema import ensure_schema


@pytest.fixture
def con():
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    con.execute(
        "insert into person values (?, ?, ?, ?, ?)",
        [1, "John Smith", date(1990, 1, 1), None, "Midfielder"],
    )
    con.execute(
        "insert into person values (?, ?, ?, ?, ?)",
        [2, "John Smith", date(1995, 6, 15), None, "Defender"],
    )
    con.execute(
        "insert into person values (?, ?, ?, ?, ?)",
        [3, "Jane Doe", None, None, "Forward"],
    )
    return con


def test_unique_match_by_name_only(con):
    person_id = resolve_person(con, "skillcorner", "sc-99", "Jane Doe")
    assert person_id == 3
    alias = con.execute(
        "select person_id, confidence from person_alias where source = ? and source_ref = ?",
        ["skillcorner", "sc-99"],
    ).fetchone()
    assert alias == (3, 1.0)


def test_ambiguous_name_goes_to_unresolved(con):
    person_id = resolve_person(con, "impect", "im-1", "John Smith")
    assert person_id is None
    unresolved = report_unresolved(con)
    assert len(unresolved) == 1
    assert unresolved[0][:3] == ("impect", "im-1", "John Smith")
    assert "ambiguous" in unresolved[0][3]


def test_ambiguous_resolves_once_dob_disambiguates(con):
    assert resolve_person(con, "impect", "im-1", "John Smith") is None
    person_id = resolve_person(con, "impect", "im-1", "John Smith", dob=date(1995, 6, 15))
    assert person_id == 2
    assert report_unresolved(con) == []  # promoted out of unresolved_alias


def test_no_match_goes_to_unresolved(con):
    person_id = resolve_person(con, "skillcorner", "sc-404", "Nobody Here")
    assert person_id is None
    unresolved = report_unresolved(con)
    assert unresolved[0][3] == "no exact name/dob match"


def test_resolution_is_idempotent(con):
    first = resolve_person(con, "skillcorner", "sc-99", "Jane Doe")
    second = resolve_person(con, "skillcorner", "sc-99", "Jane Doe")
    assert first == second == 3
    count = con.execute(
        "select count(*) from person_alias where source = ? and source_ref = ?",
        ["skillcorner", "sc-99"],
    ).fetchone()[0]
    assert count == 1
