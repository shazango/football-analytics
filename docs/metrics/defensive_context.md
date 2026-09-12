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
- **defensive_shots_central_share** (v2): percentage of shots faced with
  a start location within **goal width** (`36.25 <= location_y <= 63.75`,
  our normalised 0-100 coordinates — the goalposts projected back up the
  pitch). Central shots are typically higher-quality and harder to defend
  as a unit than shots forced wide. See "Why goal width" below.
- **defensive_shots_unpressured_share**: percentage of shots faced where
  StatsBomb did *not* flag the shooter as under pressure
  (`qualifiers.UnderPressure` absent). A high share means the defence is
  regularly failing to close shooters down before they get a shot away.

## Why goal width (v2)

Inside the posts the goalkeeper is covering the frame; outside them they
are covering an angle. That is a footballing line rather than a round
number, and it is the reason for the boundary.

Shares of every shot in the Bundesliga 2023/24 warehouse (919 shots):

| Boundary | Inside |
|---|---|
| 22.5-77.5 (penalty box width) | 99.1% |
| 30-70 (v1) | 92.6% |
| **36.25-63.75 (v2, goal width)** | **71.7%** |
| 40-60 | 56.0% |

### What v1 got wrong

The v1 boundary was the central 40% of the pitch, which contained **92.6%
of every shot in the dataset**. A metric that answers "yes" to nine
shots in ten cannot separate one goalkeeper from another: the only two
keepers in this slice facing 20 or more shots sat at 90.5% and 95.0%, a
4.5-point range on a 0-100 scale.

Worse, it communicated the opposite of what it measured. Hrádecký's v1
value was **90.5%, which is below the dataset average of 92.6%** — his
shot mix was slightly *less* central than typical. The report rendered
"90.5%" with no distribution behind it, and any reader would take that as
"almost everything he faced was central". The number was confident,
correctly computed, and pointed the wrong way.

That is the same failure class as `tackles` reading 0.00 for every player
and as the ordinal template printing "82th of 60": output that renders
without complaint and misinforms. It is recorded here because the pattern
matters more than the individual bug — a value being arithmetically right
is not evidence that it says anything.

### Version note

Only `defensive_shots_central_share` is bumped to v2.
`defensive_xg_per_shot_faced` and `defensive_shots_unpressured_share`
share this page but not this change, and bumping them would signal a
revision that did not happen. Stored v1 rows for the central share remain
in the ledger and are not comparable with v2 values.
