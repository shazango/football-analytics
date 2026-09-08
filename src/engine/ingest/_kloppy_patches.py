"""Workaround for a kloppy StatsBomb bug, applied on import.

kloppy's `parse_freeze_frame` (infra/serializers/event/statsbomb/helpers.py)
always adds `event.player` as a key into `Frame.players_data` (its final
catch-all line), and separately returns `event.player` for any freeze-frame
entry flagged `"actor": true`. Some event types that still carry 360 frames
(e.g. "Referee Ball-Drop") have no player, so `event.player` is None —
either path puts a literal `None` key into `players_data`, and kloppy's own
goalkeeper-identification pass then crashes on `None.attributes`
(deserializer.py:125). Confirmed against the Bundesliga 2023/24 open-data
release (2 of 34 matches hit this).

This is a copy of kloppy's function with both spots guarded against
event.player being None. Delete this file if kloppy fixes it upstream.
"""

from typing import Optional

from kloppy.domain import Player, PlayerData, Point3D, Team
from kloppy.domain.services.frame_factory import create_frame
from kloppy.infra.serializers.event.statsbomb import deserializer as _sb_deserializer
from kloppy.infra.serializers.event.statsbomb.helpers import parse_coordinates


def _patched_parse_freeze_frame(
    freeze_frame: list[dict],
    fidelity_version: int,
    home_team: Team,
    away_team: Team,
    event,
    visible_area: Optional[list] = None,
):
    players_data = {}

    def get_player_from_freeze_frame(player_data, team, i):
        if "player" in player_data:
            home_player = home_team.get_player_by_id(player_data["player"]["id"])
            if home_player:
                return home_player
            away_player = away_team.get_player_by_id(player_data["player"]["id"])
            if away_player:
                return away_player

        if player_data.get("actor") and event.player is not None:
            return event.player
        elif player_data.get("keeper"):
            return Player(
                player_id=f"T{team.team_id}-E{event.event_id}-{i}",
                team=team,
                jersey_no=None,
                attributes={"goalkeeper": True},
            )
        else:
            return Player(
                player_id=f"T{team.team_id}-E{event.event_id}-{i}",
                team=team,
                jersey_no=None,
                attributes={"goalkeeper": False},
            )

    for i, freeze_frame_player in enumerate(freeze_frame):
        is_teammate = (event.team == home_team) == freeze_frame_player["teammate"]
        freeze_frame_team = home_team if is_teammate else away_team
        player = get_player_from_freeze_frame(freeze_frame_player, freeze_frame_team, i)
        players_data[player] = PlayerData(
            coordinates=parse_coordinates(
                freeze_frame_player["location"], fidelity_version
            )
        )

    if event.player is not None and event.player not in players_data:
        players_data[event.player] = PlayerData(coordinates=event.coordinates)

    frame_id = int(
        event.period.start_timestamp.total_seconds()
        + event.timestamp.total_seconds() * 25
    )
    return create_frame(
        frame_id=frame_id,
        ball_coordinates=Point3D(x=event.coordinates.x, y=event.coordinates.y, z=0),
        players_data=players_data,
        period=event.period,
        timestamp=event.timestamp,
        ball_state=event.ball_state,
        ball_owning_team=event.ball_owning_team,
        other_data={"visible_area": visible_area},
    )


_sb_deserializer.parse_freeze_frame = _patched_parse_freeze_frame
