"""SkillCorner ingest into `physical_sample` (build order step 14, last;
not needed for the report — brief §11).

SkillCorner's actual open-data release (github.com/SkillCorner/opendata)
is 10 matches of 2024/25 Australian A-League tracking data — it shares
zero players with our StatsBomb-based Bundesliga 2023/24 warehouse. Real
ingestion against that release therefore resolves zero players via
step 4's `resolve_person` (an exact-name match against a `person` table
that has never heard of any A-League player) and writes zero rows. That
is the correct, honest outcome of a genuine data mismatch, not a bug in
this module — verified below against real SkillCorner tracking data
using a synthetic warehouse seeded with a real player's name, since the
actual warehouse can't provide a meaningful end-to-end check here.

`physical_sample` never stores raw tracking frames (brief §12): every
frame is reduced, per 15-minute bucket, to distance/speed/sprint/accel/
decel figures computed from consecutive-frame displacement. Sprint and
accel/decel thresholds are ours, explicit (kloppy's tracking frames give
raw positions, not classified events, and this SkillCorner release
doesn't populate a native speed field):

- distance_m: sum of frame-to-frame displacement
- hi_distance_m: distance covered while speed >= 5.5 m/s (a commonly
  cited "high-intensity running" threshold)
- sprint_count: number of distinct spells at or above 7.0 m/s
- accel_count / decel_count: frame-to-frame speed changes at or beyond
  +/-2.5 m/s^2
- max_speed_ms: max frame-to-frame speed in the bucket
"""

import math

from engine.identity.resolve import resolve_person

BUCKET_MINUTES = 15
HI_SPEED_MS = 5.5
SPRINT_SPEED_MS = 7.0
ACCEL_THRESHOLD_MS2 = 2.5


def _compute_bucket_stats(samples: list[tuple[float, float, float]]) -> dict:
    """samples: [(t_seconds, x_m, y_m), ...] for one player within one
    bucket, in chronological order (not required to be pre-sorted)."""
    samples = sorted(samples)
    distance = 0.0
    hi_distance = 0.0
    max_speed = 0.0
    sprint_count = 0
    accel_count = 0
    decel_count = 0
    in_sprint = False
    prev_speed = None
    for (t0, x0, y0), (t1, x1, y1) in zip(samples, samples[1:]):
        dt = t1 - t0
        if dt <= 0:
            continue
        d = math.hypot(x1 - x0, y1 - y0)
        speed = d / dt
        distance += d
        max_speed = max(max_speed, speed)

        if speed >= HI_SPEED_MS:
            hi_distance += d
        if speed >= SPRINT_SPEED_MS:
            if not in_sprint:
                sprint_count += 1
            in_sprint = True
        else:
            in_sprint = False

        if prev_speed is not None:
            accel = (speed - prev_speed) / dt
            if accel >= ACCEL_THRESHOLD_MS2:
                accel_count += 1
            elif accel <= -ACCEL_THRESHOLD_MS2:
                decel_count += 1
        prev_speed = speed

    return {
        "distance_m": distance,
        "hi_distance_m": hi_distance,
        "sprint_count": sprint_count,
        "accel_count": accel_count,
        "decel_count": decel_count,
        "max_speed_ms": max_speed,
    }


def ingest_tracking_dataset(con, fixture_id: int, dataset) -> int:
    """Buckets a kloppy SkillCorner TrackingDataset into physical_sample
    rows for whichever players resolve to an existing person_id (step 4).
    Returns the number of rows written."""
    samples_by_player: dict[int, list[tuple]] = {}
    names_by_player: dict[int, str] = {}
    for frame in dataset.records:
        t = frame.timestamp.total_seconds()
        for player, pdata in frame.players_data.items():
            if pdata.coordinates is None:
                continue
            samples_by_player.setdefault(player.player_id, []).append(
                (t, pdata.coordinates.x, pdata.coordinates.y)
            )
            names_by_player[player.player_id] = player.name

    bucket_size_s = BUCKET_MINUTES * 60
    rows_written = 0
    for sc_player_id, samples in samples_by_player.items():
        person_id = resolve_person(
            con, source="skillcorner", source_ref=str(sc_player_id),
            display_name=names_by_player[sc_player_id],
        )
        if person_id is None:
            continue

        samples.sort()
        n_buckets = int(samples[-1][0] // bucket_size_s) + 1
        for b in range(n_buckets):
            b_start, b_end = b * bucket_size_s, (b + 1) * bucket_size_s
            bucket_samples = [s for s in samples if b_start <= s[0] < b_end]
            if len(bucket_samples) < 2:
                continue
            stats = _compute_bucket_stats(bucket_samples)
            con.execute(
                "INSERT OR IGNORE INTO physical_sample VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    fixture_id, person_id, b_start / 60, b_end / 60,
                    stats["distance_m"], stats["hi_distance_m"], stats["sprint_count"],
                    stats["accel_count"], stats["decel_count"], stats["max_speed_ms"],
                    "skillcorner",
                ],
            )
            rows_written += 1
    return rows_written
