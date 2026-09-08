# defensive_xg_per_shot_faced / defensive_shots_central_share / defensive_shots_unpressured_share

The "a keeper is only as good as his defence" decomposition (brief §7.2):
three numbers describing how hard a keeper's job was, separate from
[psxg_ga](psxg_ga.md), which measures how well they did it. All three
share psxg_ga's "shots faced" scoping — on-target shots (saved or scored)
by the opposing team, across every fixture the keeper appeared in
(substitution timing ignored; see psxg_ga.md).

No adjustments, no confidence intervals — these are plain descriptive
shares/means over the shots faced this season, not a modelled quantity.

- **defensive_xg_per_shot_faced**: mean of the shot's own pre-shot xG
  (StatsBomb's model, not ours) across shots faced. High mean = the
  defence is conceding good chances, independent of whether the keeper
  then saves them.
- **defensive_shots_central_share**: percentage of shots faced with a
  start location in the central third of the pitch width
  (`30 <= location_y <= 70`, our normalised 0-100 coordinates). Central
  shots are typically higher-quality/harder to defend as a unit than
  shots forced wide.
- **defensive_shots_unpressured_share**: percentage of shots faced where
  StatsBomb did *not* flag the shooter as under pressure
  (`qualifiers.UnderPressure` absent). A high share means the defence is
  regularly failing to close shooters down before they get a shot away.
