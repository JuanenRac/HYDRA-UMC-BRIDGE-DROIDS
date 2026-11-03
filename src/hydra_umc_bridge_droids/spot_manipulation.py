# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - Spot arm: pick and place of a detected object
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""PICK_OBJECT and PLACE_OBJECT with the arm of a Spot.

The bridge never computes a grasp or an arm trajectory: the robot's own manipulation service does.
It only decides whether to ask. A PICK_OBJECT is sent only if the gate accepted it AND the object
id is one the vision node currently reports (`detected_object_ids`, given by the caller); a
PLACE_OBJECT only if the gate accepted it, the robot holds something and the point is inside the
reach limit. The sink has the shape of a thin wrapper over bosdyn-client's `ManipulationApiClient`
(`grasp_object`, `place_at`) plus a `holding()` reading of the gripper. Nothing here has run
against a real Spot.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Collection, Protocol

from .coordinator import DroidCoordinator, DroidDispatch


class SpotArmSink(Protocol):
    def holding(self) -> bool: ...
    def grasp_object(self, object_id: str) -> int: ...
    def place_at(self, x: float, y: float) -> int: ...


@dataclass(frozen=True)
class ArmResult:
    sent: bool
    reason: str
    command_id: int | None = None


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class SpotArmControl:
    def pick(self, sink: SpotArmSink, dispatch: DroidDispatch, *, detected_object_ids: Collection[str]) -> ArmResult:
        if not dispatch.accepted:
            return ArmResult(False, dispatch.reason)
        if dispatch.action != DroidCoordinator.PICK_OBJECT:
            return ArmResult(False, f"pick cannot act on a {dispatch.action} dispatch")
        object_id = dispatch.parameters.get("object_id")
        if not isinstance(object_id, str) or not object_id:
            return ArmResult(False, "the PICK_OBJECT dispatch carries no validated object_id")
        if object_id not in detected_object_ids:
            return ArmResult(False, f"object {object_id!r} is not reported by the vision node, nothing is grasped")
        try:
            if sink.holding():
                return ArmResult(False, "the gripper already holds something")
            return ArmResult(True, "sent", sink.grasp_object(object_id))
        except Exception as error:
            return ArmResult(False, f"Spot manipulation failed: {error}")

    def place(self, sink: SpotArmSink, dispatch: DroidDispatch, *, max_reach_m: float) -> ArmResult:
        if not dispatch.accepted:
            return ArmResult(False, dispatch.reason)
        if dispatch.action != DroidCoordinator.PLACE_OBJECT:
            return ArmResult(False, f"place cannot act on a {dispatch.action} dispatch")
        x, y = dispatch.parameters.get("x"), dispatch.parameters.get("y")
        if not (_finite(x) and _finite(y)):
            return ArmResult(False, "the PLACE_OBJECT dispatch carries no validated finite x and y")
        if not _finite(max_reach_m) or max_reach_m <= 0:
            return ArmResult(False, f"max_reach_m must be a finite, positive number, got {max_reach_m!r}")
        distance = math.hypot(x, y)  # type: ignore[arg-type]
        if distance > max_reach_m:
            return ArmResult(False, f"the point is {distance:.2f} m away, beyond the {max_reach_m:g} m reach")
        try:
            if not sink.holding():
                return ArmResult(False, "the gripper holds nothing to place")
            return ArmResult(True, "sent", sink.place_at(float(x), float(y)))  # type: ignore[arg-type]
        except Exception as error:
            return ArmResult(False, f"Spot manipulation failed: {error}")
