# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - Platform capability profiles and simulated droid
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Which action triggers a platform can be asked for, and a droid that cannot move.

A profile is the minimum a platform must support for an action to be
forwarded to it at all: an action outside the profile is refused here
instead of being sent to hardware that has no such capability.
`SimulatedDroid` follows a profile with pure bookkeeping - it imports no
transport and cannot produce real motion - so a job can be rehearsed end to
end before a real platform is connected.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .coordinator import DroidCoordinator, DroidDispatch

_C = DroidCoordinator
_POSTURE_AND_MOTION = frozenset({_C.WALK_TO, _C.RETURN_HOME, _C.HOLD_POSITION, _C.STAND, _C.SIT})


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class ForbiddenZone:
    """A rectangle, in the frame of the WALK_TO goal (metres, the body frame of the robot), that a walk may neither end in nor cross."""

    name: str
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("a forbidden zone needs a name")
        if not all(_finite(v) for v in (self.x_min, self.y_min, self.x_max, self.y_max)):
            raise ValueError(f"forbidden zone {self.name!r}: every bound must be a finite number")
        if self.x_min > self.x_max or self.y_min > self.y_max:
            raise ValueError(f"forbidden zone {self.name!r}: a minimum is above its maximum")

    def blocks(self, goal_x: float, goal_y: float) -> bool:
        """True when the straight walk from the robot (the origin) to the goal ends inside the zone or crosses it."""
        t_enter, t_leave = 0.0, 1.0
        for start, delta, low, high in ((0.0, goal_x, self.x_min, self.x_max), (0.0, goal_y, self.y_min, self.y_max)):
            if delta == 0.0:
                if not low <= start <= high:
                    return False
                continue
            near, far = (low - start) / delta, (high - start) / delta
            if near > far:
                near, far = far, near
            t_enter, t_leave = max(t_enter, near), min(t_leave, far)
            if t_enter > t_leave:
                return False
        return True


@dataclass(frozen=True)
class PlatformProfile:
    name: str
    actions: frozenset[str]
    # The farthest a single WALK_TO may go from where the robot stands, in metres.
    # None means the profile sets no limit (a deployment sets its own).
    max_walk_distance_m: float | None = None
    # The fastest the robot may walk, in metres per second; None means no limit. A walk that has to be limited and cannot be is refused.
    max_speed_mps: float | None = None
    # Places a walk may not end in or cross; empty means none.
    forbidden_zones: tuple[ForbiddenZone, ...] = ()

    def __post_init__(self) -> None:
        for what, value in (("max_walk_distance_m", self.max_walk_distance_m), ("max_speed_mps", self.max_speed_mps)):
            if value is not None and (not _finite(value) or value <= 0):
                raise ValueError(f"{what} must be a finite, positive number or None, got {value!r}")

    def walk_limits(self) -> dict[str, object]:
        """The keyword arguments of `SpotDroidControl.walk_to` that carry this profile's limits."""
        return {
            "max_distance_m": self.max_walk_distance_m,
            "max_speed_mps": self.max_speed_mps,
            "forbidden_zones": self.forbidden_zones,
        }

    def supports(self, action: str) -> bool:
        return action in self.actions


# Deliberately generic: capability shapes, not claims about any vendor's model.
MOBILE_ONLY = PlatformProfile("mobile-only", _POSTURE_AND_MOTION)
MOBILE_MANIPULATOR = PlatformProfile("mobile-manipulator", _POSTURE_AND_MOTION | {_C.PICK_OBJECT, _C.PLACE_OBJECT})
PROFILES: dict[str, PlatformProfile] = {p.name: p for p in (MOBILE_ONLY, MOBILE_MANIPULATOR)}


def check_against_profile(dispatch: DroidDispatch, profile: PlatformProfile) -> DroidDispatch:
    """Return `dispatch` unchanged when the profile supports its action, else a refusal.

    HOLD_POSITION is always kept: a stop must never be blocked by a
    capability check.
    """

    if not dispatch.accepted or dispatch.action == _C.HOLD_POSITION or profile.supports(dispatch.action):
        return dispatch
    return DroidDispatch(False, dispatch.action, f"platform profile {profile.name!r} does not support {dispatch.action}", dispatch.mode)


class SimulatedDroid:
    """Records the actions a profile accepts; performs no real motion."""

    def __init__(self, profile: PlatformProfile) -> None:
        self._profile = profile
        self._executed: list[str] = []

    @property
    def executed(self) -> tuple[str, ...]:
        return tuple(self._executed)

    def apply(self, dispatch: DroidDispatch) -> DroidDispatch:
        checked = check_against_profile(dispatch, self._profile)
        if checked.accepted:
            self._executed.append(checked.action)
        return checked
