"""Step 11: pure Impect alignment/parsing logic — no network calls (the
actual fetch functions are exercised once, by hand, for the real
validation documented in docs/metrics/line_break_value.md)."""

from datetime import datetime

import pytest

from engine.ingest.impect import align_fixtures, player_kpi_values


def test_align_fixtures_pairs_by_date_order():
    statsbomb_fixtures = [
        (2001, datetime(2023, 9, 2, 16, 30), 1, 2),
        (2000, datetime(2023, 8, 19, 16, 30), 1, 3),
    ]
    impect_matches = [
        {"id": 900, "homeSquadId": 41, "awaySquadId": 37, "scheduledDate": "2023-08-19T13:30:00Z"},
        {"id": 901, "homeSquadId": 41, "awaySquadId": 36, "scheduledDate": "2023-09-02T13:30:00Z"},
        {"id": 999, "homeSquadId": 5, "awaySquadId": 6, "scheduledDate": "2023-08-20T13:30:00Z"},  # other club
    ]
    mapping = align_fixtures(statsbomb_fixtures, impect_matches, squad_id=41)
    assert mapping == {2000: 900, 2001: 901}


def test_align_fixtures_raises_on_count_mismatch():
    statsbomb_fixtures = [(2000, datetime(2023, 8, 19, 16, 30), 1, 3)]
    impect_matches = [
        {"id": 900, "homeSquadId": 41, "awaySquadId": 37, "scheduledDate": "2023-08-19T13:30:00Z"},
        {"id": 901, "homeSquadId": 41, "awaySquadId": 36, "scheduledDate": "2023-09-02T13:30:00Z"},
    ]
    with pytest.raises(ValueError, match="fixture count mismatch"):
        align_fixtures(statsbomb_fixtures, impect_matches, squad_id=41)


def test_player_kpi_values_merges_both_squads():
    match_kpis = {
        "matchId": 900,
        "squadHome": {"id": 41, "players": [{"id": 1, "kpis": [{"kpiId": 0, "value": 3.0}]}]},
        "squadAway": {"id": 37, "players": [{"id": 2, "kpis": [{"kpiId": 83, "value": 0.5}]}]},
    }
    result = player_kpi_values(match_kpis)
    assert result == {1: {0: 3.0}, 2: {83: 0.5}}
