"""Fetch raw StatsBomb open-data files to a local cache.

Mirrors the source repo's own path layout (data/competitions.json,
data/matches/<cid>/<sid>.json, data/events/<mid>.json, ...) so the same
kloppy-loading code in statsbomb.py works unchanged against either a real
download directory or the trimmed fixture tree in tests/fixtures/.

Downloaded files are a local cache only (gitignored, see data/) — never
committed, never treated as the persisted store. The canonical DuckDB
tables in warehouse/ are the actual deliverable (PHASE-0-BRIEF.md §12:
never persist raw third-party payloads).
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import certifi

# ponytail: this Python.org build doesn't trust the macOS system CA store
# the way curl does, so urllib fails TLS verification without this. Only
# sets it if the environment hasn't already got a cert file configured.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

BASE_URL = "https://raw.githubusercontent.com/hudl/open-data/master/data"
DEFAULT_DATA_DIR = Path("data/statsbomb/data")


def _fetch(url: str, dest: Path) -> bool:
    """Download url to dest if not already cached. Returns False on 404."""
    if dest.exists():
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(url, dest)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise
    return True


def download_competition(
    competition_id: int, season_id: int, data_dir: Path = DEFAULT_DATA_DIR
) -> list[int]:
    """Download competitions.json, the match list, and each match's events/
    lineups/three-sixty. Returns the list of match ids downloaded.
    """
    _fetch(f"{BASE_URL}/competitions.json", data_dir / "competitions.json")

    matches_path = data_dir / "matches" / str(competition_id) / f"{season_id}.json"
    _fetch(
        f"{BASE_URL}/matches/{competition_id}/{season_id}.json", matches_path
    )
    matches = json.loads(matches_path.read_text())
    match_ids = [m["match_id"] for m in matches]

    for mid in match_ids:
        _fetch(f"{BASE_URL}/events/{mid}.json", data_dir / "events" / f"{mid}.json")
        _fetch(f"{BASE_URL}/lineups/{mid}.json", data_dir / "lineups" / f"{mid}.json")
        _fetch(
            f"{BASE_URL}/three-sixty/{mid}.json",
            data_dir / "three-sixty" / f"{mid}.json",
        )

    return match_ids
