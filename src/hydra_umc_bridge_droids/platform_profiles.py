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

from dataclasses import dataclass

from .coordinator import DroidCoordinator, DroidDispatch

_C = DroidCoordinator
_POSTURE_AND_MOTION = frozenset({_C.WALK_TO, _C.RETURN_HOME, _C.HOLD_POSITION, _C.STAND, _C.SIT})


@dataclass(frozen=True)
class PlatformProfile:
    name: str
    actions: frozenset[str]

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
