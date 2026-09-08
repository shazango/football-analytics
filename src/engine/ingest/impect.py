"""Fetch Impect open-data reference numbers (build order step 11).

Used only to validate line_break_value against Impect's own packing /
packing-xG KPIs for the same players — not ingested into the canonical
schema. `metric_value` doesn't get rows from this data; it's a transient
cross-check, cached locally like StatsBomb's downloads
(data/impect/, gitignored) but never persisted into the warehouse.

Impect's open-data release covers the *entire* Bundesliga 2023/24 season
(306 matches, all 18 clubs) as one "iteration" (id 743) — unlike
StatsBomb's single-club-season slice. We only ever need the 34 matches
involving Bayer Leverkusen (squad id 41), to match what's already
ingested.
"""

import json
import os
import urllib.request
from pathlib import Path

import certifi

# ponytail: same TLS quirk as download.py (this machine's Python doesn't
# trust the system CA store the way curl does).
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

BASE_URL = "https://raw.githubusercontent.com/ImpectAPI/open-data/main/data"
DEFAULT_DATA_DIR = Path("data/impect")
BUNDESLIGA_2023_24_ITERATION = 743
LEVERKUSEN_SQUAD_ID = 41

KPI_BYPASSED_OPPONENTS = 0
KPI_PACKING_XG = 83


def _fetch_json(url: str, dest: Path) -> object:
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, dest)
    return json.loads(dest.read_text())


def matches(iteration_id: int = BUNDESLIGA_2023_24_ITERATION, data_dir: Path = DEFAULT_DATA_DIR) -> list[dict]:
    return _fetch_json(
        f"{BASE_URL}/matches/matches_{iteration_id}.json", data_dir / f"matches_{iteration_id}.json"
    )


def squads(iteration_id: int = BUNDESLIGA_2023_24_ITERATION, data_dir: Path = DEFAULT_DATA_DIR) -> list[dict]:
    return _fetch_json(
        f"{BASE_URL}/squads/squads_{iteration_id}.json", data_dir / f"squads_{iteration_id}.json"
    )


def players(iteration_id: int = BUNDESLIGA_2023_24_ITERATION, data_dir: Path = DEFAULT_DATA_DIR) -> list[dict]:
    return _fetch_json(
        f"{BASE_URL}/players/players_{iteration_id}.json", data_dir / f"players_{iteration_id}.json"
    )


def player_kpis(match_id: int, data_dir: Path = DEFAULT_DATA_DIR) -> dict:
    return _fetch_json(
        f"{BASE_URL}/player_kpis/player_kpis_{match_id}.json", data_dir / f"player_kpis_{match_id}.json"
    )


def leverkusen_match_ids(
    iteration_id: int = BUNDESLIGA_2023_24_ITERATION, data_dir: Path = DEFAULT_DATA_DIR
) -> list[int]:
    all_matches = matches(iteration_id, data_dir)
    lev = [
        m for m in all_matches
        if m["homeSquadId"] == LEVERKUSEN_SQUAD_ID or m["awaySquadId"] == LEVERKUSEN_SQUAD_ID
    ]
    return [m["id"] for m in sorted(lev, key=lambda m: m["scheduledDate"])]


def align_fixtures(statsbomb_fixtures: list[tuple], impect_matches: list[dict],
                    squad_id: int = LEVERKUSEN_SQUAD_ID) -> dict[int, int]:
    """Maps statsbomb fixture_id -> impect match_id for one club's season,
    by pairing both providers' match lists sorted by date. There's no
    shared id to join on (Impect's idMappings carry heim_spiel/skill_corner
    references, not StatsBomb) — verified instead that both list exactly
    34 Leverkusen 2023/24 matches, and that the first pair (2023-08-19,
    Leverkusen home vs. RB Leipzig on both sides) lines up — see
    docs/metrics/line_break_value.md.

    statsbomb_fixtures: (fixture_id, kickoff, home_team_id, away_team_id).
    """
    lev_impect = sorted(
        (m for m in impect_matches if m["homeSquadId"] == squad_id or m["awaySquadId"] == squad_id),
        key=lambda m: m["scheduledDate"],
    )
    sb_sorted = sorted(statsbomb_fixtures, key=lambda f: f[1])
    if len(lev_impect) != len(sb_sorted):
        raise ValueError(
            f"fixture count mismatch: {len(sb_sorted)} StatsBomb fixtures, "
            f"{len(lev_impect)} Impect matches for squad {squad_id}"
        )
    return {sb[0]: im["id"] for sb, im in zip(sb_sorted, lev_impect)}


def player_kpi_values(match_player_kpis: dict) -> dict[int, dict[int, float]]:
    """{impect_player_id: {kpi_id: value}} for both squads in one match."""
    out: dict[int, dict[int, float]] = {}
    for squad_key in ("squadHome", "squadAway"):
        for player in match_player_kpis[squad_key]["players"]:
            out[player["id"]] = {k["kpiId"]: k["value"] for k in player["kpis"]}
    return out
