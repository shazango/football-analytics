"""psxg_ga and defensive context (PHASE-0-BRIEF.md §7.2, build order step 8).

Post-shot xG (PSxG) differs from the shot's own pre-shot "xG" (already
stored per shot, from StatsBomb's model): PSxG asks "given where this shot
actually ended up, the keeper's position, and the traffic in front of
goal, how likely was it to go in" — a model of save difficulty, not shot
quality. `psxg_ga` (PSxG minus goals allowed) then measures shot-stopping:
positive means the keeper prevented more than an average keeper would
have, facing identical shots.

Trained here, on this warehouse's own on-target shots (SAVED/GOAL) —
"train the post-shot model on the open data" per brief. See
docs/metrics/psxg_ga.md for training set size and cross-validated
performance; the model is a plain logistic regression, deliberately not
anything fancier, given how few on-target shots a single competition-
season provides.

Defensive context (mean xG faced, share from central zones, share
unpressured) is a separate, simpler thing: it describes how hard the
keeper's job was, not how well they did it. Same "shots faced" scoping as
psxg_ga, no model involved.
"""

import json
import math
import random
from dataclasses import dataclass

from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from engine.metrics import registry
from engine.metrics.foundation import _appearances
from engine.metrics.runtime import MetricResult

GOAL_X = 100.0
GOAL_CENTER_Y = 50.0
POST_Y_LOW = 45.0
POST_Y_HIGH = 55.0
TRAFFIC_CORRIDOR_WIDTH = 5.0  # perpendicular distance (of 100) counted as "in the way"
CENTRAL_ZONE_Y_LOW = 30.0
CENTRAL_ZONE_Y_HIGH = 70.0

FEATURE_COLUMNS = [
    "distance_to_goal",
    "angle_to_goal",
    "is_header",
    "is_other_body_part",
    "end_y_from_center",
    "end_z",
    "keeper_lateral_offset",
    "keeper_depth",
    "traffic_count",
]


def _angle_to_goal(x: float, y: float) -> float:
    a1 = math.atan2(POST_Y_LOW - y, GOAL_X - x)
    a2 = math.atan2(POST_Y_HIGH - y, GOAL_X - x)
    angle = abs(a1 - a2)
    return 2 * math.pi - angle if angle > math.pi else angle


def _traffic_count(shot_x: float, shot_y: float, freeze_frame: list[dict]) -> int:
    """Count of non-keeper, non-shooter freeze-frame players standing
    between the shooter and the goal, within a fixed corridor of the
    direct line to goal centre. A simple, documented proxy — not a
    physics-accurate blocking model."""
    dx, dy = GOAL_X - shot_x, GOAL_CENTER_Y - shot_y
    length = math.hypot(dx, dy)
    if length == 0:
        return 0
    count = 0
    for p in freeze_frame:
        if p["keeper"] or p["actor"]:
            continue
        px, py = p["x"] - shot_x, p["y"] - shot_y
        proj = (px * dx + py * dy) / length
        if proj <= 0 or proj >= length:
            continue  # behind the shooter, or past the goal line
        perp = abs(px * dy - py * dx) / length
        if perp <= TRAFFIC_CORRIDOR_WIDTH:
            count += 1
    return count


def _extract_features(row: tuple) -> dict | None:
    """row: (fixture_id, sequence, team_id, actor_person_id, location_x,
    location_y, end_x, end_y, end_z, outcome, qualifiers, freeze_frame).
    Returns None if the shot has no identifiable keeper or no end height —
    both required and, per the step-2/6 ingest tests, rare to missing."""
    (_, _, _, _, x, y, _, end_y, end_z, outcome, qualifiers_json, freeze_frame_json) = row
    if end_z is None:
        return None
    # json.dumps(None) is the string "null" — truthy in Python — so an
    # `if x else default` guard on the raw column never catches "no frame
    # recorded"; always parse, then collapse a JSON null to the default.
    freeze_frame = json.loads(freeze_frame_json) or []
    keeper = next((p for p in freeze_frame if p["keeper"]), None)
    if keeper is None:
        return None

    qualifiers = json.loads(qualifiers_json) or {}
    body_part = (qualifiers.get("BodyPart") or [None])[0]
    return {
        "distance_to_goal": math.hypot(GOAL_X - x, GOAL_CENTER_Y - y),
        "angle_to_goal": _angle_to_goal(x, y),
        "is_header": 1.0 if body_part == "HEAD" else 0.0,
        "is_other_body_part": 1.0 if body_part not in ("HEAD", "LEFT_FOOT", "RIGHT_FOOT") else 0.0,
        "end_y_from_center": abs(end_y - GOAL_CENTER_Y),
        "end_z": end_z,
        "keeper_lateral_offset": abs(keeper["y"] - end_y),
        "keeper_depth": keeper["x"],
        "traffic_count": float(_traffic_count(x, y, freeze_frame)),
        "is_goal": 1.0 if outcome == "GOAL" else 0.0,
    }


def _opposing_shots_raw(con, person_id: int, competition_id: str) -> list[tuple]:
    """Raw on-target shot rows taken by the opposing team, across every
    fixture this person appeared in. Ignores substitution timing —
    keepers are rarely subbed, a deliberate Phase 0 simplification. Shared
    by psxg_ga and the defensive-context metrics: same shots, different
    things computed from them.
    """
    fixture_teams = con.execute(
        "select fixture_id, team_id from appearance where person_id = ? "
        "and fixture_id in (select id from fixture where competition_id = ?)",
        [person_id, competition_id],
    ).fetchall()
    rows = []
    for fixture_id, own_team_id in fixture_teams:
        rows.extend(
            con.execute(
                "select fixture_id, sequence, team_id, actor_person_id, location_x, "
                "location_y, end_x, end_y, end_z, outcome, qualifiers, freeze_frame "
                "from event where fixture_id = ? and type = 'SHOT' "
                "and outcome in ('SAVED', 'GOAL') and team_id != ?",
                [fixture_id, own_team_id],
            ).fetchall()
        )
    return rows


def _shots_faced_features(con, person_id: int, competition_id: str) -> list[dict]:
    rows = _opposing_shots_raw(con, person_id, competition_id)
    return [f for f in (_extract_features(r) for r in rows) if f is not None]


# --- model training ---------------------------------------------------------

@dataclass
class PSxGModel:
    pipeline: object
    n_shots: int
    n_goals: int
    cv_brier_score: float
    cv_log_loss: float


_MODEL_CACHE: dict[str, PSxGModel] = {}


def train_psxg_model(con, competition_id: str) -> PSxGModel:
    rows = con.execute(
        "select fixture_id, sequence, team_id, actor_person_id, location_x, location_y, "
        "end_x, end_y, end_z, outcome, qualifiers, freeze_frame from event "
        "where type = 'SHOT' and outcome in ('SAVED', 'GOAL') "
        "and fixture_id in (select id from fixture where competition_id = ?)",
        [competition_id],
    ).fetchall()
    features = [f for f in (_extract_features(r) for r in rows) if f is not None]

    x = [[f[c] for c in FEATURE_COLUMNS] for f in features]
    y = [f["is_goal"] for f in features]

    pipeline = Pipeline([("scaler", StandardScaler()), ("clf", LogisticRegression(max_iter=1000))])

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=0)
    cv_probs = cross_val_predict(pipeline, x, y, cv=cv, method="predict_proba")[:, 1]

    pipeline.fit(x, y)  # final model trained on all available data

    return PSxGModel(
        pipeline=pipeline,
        n_shots=len(y),
        n_goals=int(sum(y)),
        cv_brier_score=brier_score_loss(y, cv_probs),
        cv_log_loss=log_loss(y, cv_probs),
    )


def get_psxg_model(con, competition_id: str) -> PSxGModel:
    # ponytail: in-process cache only, keyed by competition_id — fine while
    # Phase 0 has exactly one; re-key or persist if that ever changes.
    if competition_id not in _MODEL_CACHE:
        _MODEL_CACHE[competition_id] = train_psxg_model(con, competition_id)
    return _MODEL_CACHE[competition_id]


def predict_psxg(model: PSxGModel, features: dict) -> float:
    x = [[features[c] for c in FEATURE_COLUMNS]]
    return float(model.pipeline.predict_proba(x)[0, 1])


# --- psxg_ga -----------------------------------------------------------------

def _psxg_ga_impl(con, definition, person_id, competition_id, season, fixture_id=None,
                   adjustment="per_90", **_):
    if adjustment not in ("raw", "per_90"):
        raise ValueError(f"unknown adjustment mode '{adjustment}'")
    if adjustment != "raw" and adjustment not in definition.adjustments:
        raise ValueError(
            f"metric '{definition.id}' does not declare support for "
            f"adjustment '{adjustment}' (declares {definition.adjustments})"
        )

    model = get_psxg_model(con, competition_id)
    shots = _shots_faced_features(con, person_id, competition_id)
    n = len(shots)
    if n == 0:
        return MetricResult(value=None, sample_size=0)

    psxg_values = [predict_psxg(model, f) for f in shots]
    goals = [f["is_goal"] for f in shots]
    total_minutes = sum(minutes for _, minutes, _ in _appearances(con, person_id, competition_id))

    def _aggregate(indices) -> float:
        total = sum(psxg_values[i] - goals[i] for i in indices)
        if adjustment == "per_90":
            return (total / (total_minutes / 90)) if total_minutes else 0.0
        return total

    value = _aggregate(range(n))

    # Bootstrap CI: resample shots faced with replacement (brief §6/§7.2 —
    # shot-stopping is high variance, never render a bare point estimate).
    rng = random.Random(0)
    boot_values = sorted(
        _aggregate([rng.randrange(n) for _ in range(n)]) for _ in range(1000)
    )
    ci_low = boot_values[24]  # 2.5th percentile of 1000 resamples
    ci_high = boot_values[974]  # 97.5th percentile

    return MetricResult(value=value, sample_size=n, ci_low=ci_low, ci_high=ci_high)


registry.register("psxg_ga")(_psxg_ga_impl)


# --- defensive context -------------------------------------------------------

def _make_defensive_context_impl(kind: str):
    def impl(con, definition, person_id, competition_id, season, fixture_id=None, **_):
        rows = _opposing_shots_raw(con, person_id, competition_id)
        n = len(rows)
        if n == 0:
            return MetricResult(value=None, sample_size=0)

        if kind == "mean_xg":
            xgs = []
            for row in rows:
                qualifiers = json.loads(row[10]) or {}
                if "xG" in qualifiers:
                    xgs.append(qualifiers["xG"])
            value = sum(xgs) / len(xgs) if xgs else None
        elif kind == "central_share":
            central = sum(1 for row in rows if CENTRAL_ZONE_Y_LOW <= row[5] <= CENTRAL_ZONE_Y_HIGH)
            value = 100.0 * central / n
        else:  # unpressured_share
            unpressured = sum(
                1 for row in rows
                if not (json.loads(row[10]) or {}).get("UnderPressure")
            )
            value = 100.0 * unpressured / n

        return MetricResult(value=value, sample_size=n)

    return impl


registry.register("defensive_xg_per_shot_faced")(_make_defensive_context_impl("mean_xg"))
registry.register("defensive_shots_central_share")(_make_defensive_context_impl("central_share"))
registry.register("defensive_shots_unpressured_share")(_make_defensive_context_impl("unpressured_share"))
