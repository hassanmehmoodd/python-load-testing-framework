"""Load-profile stage plans consumed by a Locust LoadTestShape."""

from dataclasses import dataclass

PROFILE_DESCRIPTIONS = {
    "constant": "Hold the configured user count for the full duration.",
    "ramp": "Step the user count up to the target across the run (ramp-up).",
    "stress": "Climb to the target user count and hold that peak.",
    "spike": "Hold a low baseline, jump to the target, then return to baseline.",
    "endurance": (
        "Reach the target quickly and hold it. The shipped duration is a short "
        "demo, not a multi-hour soak."
    ),
}

# (fraction of duration when the stage ends, fraction of configured users)
PROFILE_SHAPES: dict[str, tuple[tuple[float, float], ...]] = {
    "constant": ((1.0, 1.0),),
    "ramp": ((0.25, 0.25), (0.50, 0.50), (0.75, 0.75), (1.0, 1.0)),
    "stress": ((0.15, 0.25), (0.30, 0.50), (0.45, 0.75), (0.60, 1.0), (1.0, 1.0)),
    "spike": ((0.35, 0.20), (0.60, 1.0), (1.0, 0.20)),
    "endurance": ((0.15, 1.0), (1.0, 1.0)),
}


@dataclass(frozen=True)
class Stage:
    """One step of a load shape. ``end`` is seconds from the start of the run."""

    end: float
    users: int
    spawn_rate: float

    def as_dict(self) -> dict[str, float | int]:
        return {"end": self.end, "users": self.users, "spawn_rate": self.spawn_rate}


def build_stages(
    profile: str,
    *,
    users: int,
    spawn_rate: float,
    duration_seconds: float,
) -> list[Stage]:
    """Build a monotonic stage list that ends at ``duration_seconds``."""
    if profile not in PROFILE_SHAPES:
        known = ", ".join(sorted(PROFILE_SHAPES))
        raise ValueError(f"Unknown profile {profile!r}. Expected one of: {known}.")
    if users < 1:
        raise ValueError("users must be >= 1")
    if spawn_rate <= 0:
        raise ValueError("spawn_rate must be > 0")
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be > 0")

    spec = PROFILE_SHAPES[profile]
    preliminary: list[Stage] = []
    for index, (time_ratio, user_ratio) in enumerate(spec):
        if index == len(spec) - 1:
            end = float(duration_seconds)
        else:
            end = round(float(duration_seconds) * time_ratio, 3)
        stage_users = min(users, max(1, int(round(users * user_ratio))))
        preliminary.append(Stage(end=end, users=stage_users, spawn_rate=float(spawn_rate)))

    cleaned: list[Stage] = []
    for stage in preliminary:
        if cleaned and stage.end <= cleaned[-1].end:
            cleaned[-1] = stage
            continue
        cleaned.append(stage)
    if cleaned[-1].end != float(duration_seconds):
        last = cleaned[-1]
        cleaned[-1] = Stage(float(duration_seconds), last.users, last.spawn_rate)
    return cleaned
