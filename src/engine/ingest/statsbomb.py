"""Ingest a StatsBomb open-data competition/season into the canonical schema.

Build order steps 2-3 (PHASE-0-BRIEF.md §11): download raw files, parse with
kloppy (do not hand-roll a StatsBomb parser — kloppy already normalises
provider schemas and pitch coordinates), and persist only parsed/derived
rows to DuckDB, never the raw provider payload (§12). `possession_id` and
`game_state` (score margin as of just before the event) are derived from
kloppy's parsed events during the same ingest pass — see
`_possession_and_state`.

`qualifiers` and `freeze_frame` are built from kloppy's own normalised
Qualifier/Frame objects, not from StatsBomb's raw JSON sub-objects — that
keeps the "derived values only" rule even for semi-structured event detail.
The one exception that reaches into raw_event is xA (build order step 6):
StatsBomb links a shot-assist pass to the shot it created via an id
reference, which kloppy doesn't normalise; we resolve that link at ingest
and store the resulting xG value, not the id itself.
"""

import json
from pathlib import Path

import duckdb
import kloppy.statsbomb as sb
from kloppy.domain import Ground, ShotResult

from engine.ingest import _kloppy_patches  # noqa: F401 (applies patch on import)
from engine.ingest.download import DEFAULT_DATA_DIR, download_competition
from engine.metrics import foundation, line_break  # noqa: F401 (line_break registers)
from engine.metrics.benchmark import FOUNDATION_STAT_IDS, compute_roster_metrics
from engine.metrics.definitions import load_all


def _competition_row(data_dir: Path, competition_id: int, season_id: int) -> tuple:
    rows = json.loads((data_dir / "competitions.json").read_text())
    row = next(
        r
        for r in rows
        if r["competition_id"] == competition_id and r["season_id"] == season_id
    )
    return (
        f"{competition_id}-{season_id}",
        row["competition_name"],
        row["country_name"],
        None,  # tier: not present in StatsBomb open data
        row["competition_gender"],
        row["season_name"],
    )


def _clock_to_minutes(clock: str) -> float:
    mm, ss = clock.split(":")
    return int(mm) + int(ss) / 60


def _appearance_rows(
    lineup_json: list[dict], fixture_id: int, total_minutes: float
) -> list[tuple]:
    rows = []
    for team in lineup_json:
        for player in team["lineup"]:
            positions = player["positions"]
            if not positions:
                continue  # named in squad but never took the pitch
            start_min = _clock_to_minutes(positions[0]["from"])
            last_to = positions[-1]["to"]
            end_min = _clock_to_minutes(last_to) if last_to else total_minutes
            rows.append(
                (
                    fixture_id,
                    player["player_id"],
                    team["team_id"],
                    end_min - start_min,
                    start_min,
                    end_min,
                )
            )
    return rows


def _person_rows(lineup_json: list[dict]) -> list[tuple]:
    # No position here: it isn't a per-match fact. `primary_position` is
    # set once at the end of the ingest, from minutes summed over the whole
    # competition — see _set_primary_positions.
    return [
        (player["player_id"], player["player_name"], None, None, None)
        for team in lineup_json
        for player in team["lineup"]
    ]


def _position_minutes(
    lineup_json: list[dict], total_minutes: float
) -> list[tuple[int, str, float]]:
    """(player_id, position, minutes) for every positional stint in one
    match. A player who starts at right back and finishes in midfield
    contributes one row per shift.

    `from`/`to` are a continuous match clock, not a per-period one — a
    second-half tactical shift reads "65:26", not "20:26" — the same
    assumption _appearance_rows makes. Verified across all 805 stints in
    the Bundesliga 2023/24 slice: no stint ends before it starts.
    """
    return [
        (
            player["player_id"],
            stint["position"],
            (_clock_to_minutes(stint["to"]) if stint["to"] else total_minutes)
            - _clock_to_minutes(stint["from"]),
        )
        for team in lineup_json
        for player in team["lineup"]
        for stint in player["positions"]
    ]


def _set_primary_positions(con, minutes_by_position: dict[int, dict[str, float]]) -> None:
    """primary_position = wherever the player spent the most minutes this
    competition.

    Was "the first position listed in the first match ingested", which for
    a two-appearance opponent meant wherever he happened to stand for the
    opening ten minutes of one game — Mario Götze came out of it a
    defensive midfielder. Anyone bucketing by position (benchmark.py) is
    downstream of this, so it has to be a fact about the season, not about
    ingest order.

    Players with no stint at all (named in a squad, never took the pitch)
    are simply absent here and keep a NULL position.
    """
    con.executemany(
        "UPDATE person SET primary_position = ? WHERE id = ?",
        [
            # Ties break on the position name so a re-ingest is reproducible
            # rather than depending on which match was processed first.
            (max(by_position.items(), key=lambda kv: (kv[1], kv[0]))[0], person_id)
            for person_id, by_position in minutes_by_position.items()
        ],
    )


def _serialize_qualifiers(event, shot_xg_by_id: dict[str, float] | None = None) -> dict | None:
    # Qualifier values are collected into a list per key, not overwritten:
    # kloppy can legitimately attach more than one qualifier of the same
    # class to a single event (e.g. a StatsBomb 50/50 event's Duel
    # qualifier is both LOOSE_BALL and GROUND). A last-value-wins scalar
    # assignment here silently drops that second qualifier and made a
    # 50/50 loose-ball contest indistinguishable from a tackle (Duel=
    # GROUND either way) — see qualifier_contains in engine.metrics.foundation.
    out: dict = {}
    for q in event.qualifiers or []:
        key = type(q).__name__.replace("Qualifier", "")
        value = q.value
        out.setdefault(key, []).append(value.name if hasattr(value, "name") else value)
    # Statistics (xG and the xA override below) are single-valued per
    # event and used arithmetically downstream — kept as scalars.
    for stat in getattr(event, "statistics", None) or []:
        out[stat.name] = stat.value
    # xA: not a kloppy-native field. StatsBomb links a shot-assist pass to
    # the shot it created via assisted_shot_id; we resolve that link once
    # here and store the *value* (the linked shot's xG), not the raw id —
    # keeps the "derived values only, no raw payloads" rule (§12).
    if shot_xg_by_id and event.raw_event.get("pass", {}).get("shot_assist"):
        assisted_shot_id = event.raw_event["pass"].get("assisted_shot_id")
        if assisted_shot_id in shot_xg_by_id:
            out["xA"] = shot_xg_by_id[assisted_shot_id]
    return out or None


def _serialize_freeze_frame(event) -> list[dict] | None:
    frame = getattr(event, "freeze_frame", None)
    if frame is None:
        return None
    actor_id = event.player.player_id if event.player else None
    out = []
    for player, point in frame.players_coordinates.items():
        # StatsBomb 360 gives approximate positions for some players it
        # can't identify; kloppy synthesizes a non-numeric id for those.
        person_id = int(player.player_id) if str(player.player_id).isdigit() else None
        out.append(
            {
                "person_id": person_id,
                "x": point.x,
                "y": point.y,
                "teammate": player.team is not None and player.team == event.team,
                "actor": actor_id is not None and player.player_id == actor_id,
                "keeper": player.starting_position is not None
                and player.starting_position.name == "Goalkeeper",
            }
        )
    return out


def _end_point(event):
    # Different kloppy event classes name their end-location field
    # differently: CarryEvent/ShotEvent use end_coordinates/result_coordinates,
    # but PassEvent uses receiver_coordinates (the receiving player's spot).
    for attr in ("end_coordinates", "result_coordinates", "receiver_coordinates"):
        point = getattr(event, attr, None)
        if point is not None:
            return point
    return None


def _possession_and_state(ds, fixture_id: int) -> list[tuple[int | None, str | None]]:
    """Possession id (unique per match) and game_state (score margin for the
    event's own team, as of just before the event) for every event in order.

    `possession` is StatsBomb's own chain number (per raw_event, not a
    persisted payload — read directly off kloppy's already-parsed event);
    combined with fixture_id it's unique across the warehouse. Own goals
    credit the *opposing* team's tally, per StatsBomb's own convention of
    attributing the OWN_GOAL_AGAINST event to the conceding side.
    """
    scores = {Ground.HOME: 0, Ground.AWAY: 0}
    out = []
    for event in ds.events:
        raw_possession = event.raw_event.get("possession")
        possession_id = (
            fixture_id * 10_000 + raw_possession if raw_possession is not None else None
        )

        if event.team is None:
            game_state = None
        else:
            own_ground = event.team.ground
            opp_ground = Ground.AWAY if own_ground == Ground.HOME else Ground.HOME
            game_state = str(scores[own_ground] - scores[opp_ground])

        out.append((possession_id, game_state))

        if event.event_type.name == "SHOT" and event.result is not None:
            if event.result == ShotResult.GOAL:
                scores[event.team.ground] += 1
            elif event.result == ShotResult.OWN_GOAL:
                conceding = event.team.ground
                scoring = Ground.AWAY if conceding == Ground.HOME else Ground.HOME
                scores[scoring] += 1
    return out


def _event_rows(ds, fixture_id: int) -> list[tuple]:
    period_offset_ms = {
        p.id: p.start_timestamp.total_seconds() * 1000 for p in ds.metadata.periods
    }
    possession_and_state = _possession_and_state(ds, fixture_id)
    shot_xg_by_id = {
        event.event_id: stat.value
        for event in ds.events
        if event.event_type.name == "SHOT"
        for stat in (event.statistics or [])
        if stat.name == "xG"
    }
    rows = []
    for sequence, (event, (possession_id, game_state)) in enumerate(
        zip(ds.events, possession_and_state)
    ):
        end_point = _end_point(event)
        rows.append(
            (
                fixture_id,
                sequence,
                period_offset_ms[event.period.id] + event.timestamp.total_seconds() * 1000,
                event.period.id,
                event.event_type.name,
                event.player.player_id if event.player else None,
                event.team.team_id if event.team else None,
                event.coordinates.x if event.coordinates else None,
                event.coordinates.y if event.coordinates else None,
                end_point.x if end_point else None,
                end_point.y if end_point else None,
                getattr(end_point, "z", None),
                event.result.name if event.result else None,
                possession_id,
                json.dumps(_serialize_qualifiers(event, shot_xg_by_id)),
                game_state,
                json.dumps(_serialize_freeze_frame(event)),
            )
        )
    return rows


def ingest_competition(
    con: duckdb.DuckDBPyConnection,
    competition_id: int,
    season_id: int,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> None:
    match_ids = download_competition(competition_id, season_id, data_dir)

    competition_row = _competition_row(data_dir, competition_id, season_id)
    con.execute(
        "INSERT OR IGNORE INTO competition VALUES (?, ?, ?, ?, ?, ?)",
        competition_row,
    )
    competition_row_id = f"{competition_id}-{season_id}"
    season_name = competition_row[5]

    matches = json.loads(
        (data_dir / "matches" / str(competition_id) / f"{season_id}.json").read_text()
    )
    matches_by_id = {m["match_id"]: m for m in matches}

    minutes_by_position: dict[int, dict[str, float]] = {}

    for mid in match_ids:
        match = matches_by_id[mid]
        for side in ("home_team", "away_team"):
            con.execute(
                "INSERT OR IGNORE INTO team VALUES (?, ?, ?)",
                (
                    match[side][f"{side}_id"],
                    match[side][f"{side}_name"],
                    competition_row_id,
                ),
            )
        con.execute(
            "INSERT OR IGNORE INTO fixture VALUES (?, ?, ?, ?, ?)",
            (
                mid,
                competition_row_id,
                match["home_team"]["home_team_id"],
                match["away_team"]["away_team_id"],
                f"{match['match_date']} {match['kick_off']}"
                if match.get("kick_off")
                else None,
            ),
        )

        events_path = data_dir / "events" / f"{mid}.json"
        lineup_path = data_dir / "lineups" / f"{mid}.json"
        three_sixty_path = data_dir / "three-sixty" / f"{mid}.json"

        ds = sb.load(
            event_data=events_path,
            lineup_data=lineup_path,
            three_sixty_data=three_sixty_path if three_sixty_path.exists() else None,
            coordinates="opta",
        )

        lineup_json = json.loads(lineup_path.read_text())
        total_minutes = ds.metadata.periods[-1].end_timestamp.total_seconds() / 60

        con.executemany(
            "INSERT OR IGNORE INTO person VALUES (?, ?, ?, ?, ?)",
            _person_rows(lineup_json),
        )
        for person_id, position, minutes in _position_minutes(lineup_json, total_minutes):
            minutes_by_position.setdefault(person_id, {})
            minutes_by_position[person_id][position] = (
                minutes_by_position[person_id].get(position, 0.0) + minutes
            )
        con.executemany(
            "INSERT OR IGNORE INTO appearance VALUES (?, ?, ?, ?, ?, ?)",
            _appearance_rows(lineup_json, mid, total_minutes),
        )
        con.executemany(
            "INSERT OR IGNORE INTO event VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _event_rows(ds, mid),
        )

    _set_primary_positions(con, minutes_by_position)

    foundation.assert_qualifier_values_seen(con)

    # Populate metric_value for the whole roster now, not lazily per report:
    # compute_benchmark (build order step 7) reads whatever's already stored
    # for a bucket/metric, so a report generated before this ran would only
    # ever benchmark against whichever players happened to have a report of
    # their own generated earlier — never the actual roster.
    defs = load_all()
    compute_roster_metrics(
        con, {sid: defs[sid] for sid in FOUNDATION_STAT_IDS}, competition_row_id, season_name
    )


def _main() -> None:
    import argparse

    from engine.model.db import connect

    parser = argparse.ArgumentParser()
    parser.add_argument("--competition-id", type=int, required=True)
    parser.add_argument("--season-id", type=int, required=True)
    args = parser.parse_args()

    con = connect()
    ingest_competition(con, args.competition_id, args.season_id)
    n_fixtures, n_events = con.execute(
        "select (select count(*) from fixture), (select count(*) from event)"
    ).fetchone()
    print(f"Ingested {n_fixtures} fixtures, {n_events} events into {con!r}")


if __name__ == "__main__":
    _main()
