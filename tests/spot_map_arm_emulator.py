# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - Emulated GraphNav map and arm of a Spot
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""A GraphNav map and a manipulation arm that follow the state of the emulated robot.

`SpotMapEmulator` has the shape of `SpotGraphNavSink` and `SpotArmEmulator` the shape of
`SpotArmSink`. Both read the posture, the motor power and the emergency stop of a
`SpotRobotEmulator`, so a navigation or a grasp that is under way fails the way a real
one would when the stop is engaged. Everything here is a model written from the public
description of the client library: it is not a recording of a real Spot.
"""

from __future__ import annotations

import time

from spot_emulator import SpotRobotEmulator


class SpotMapEmulator:
    """Named waypoints, one navigation at a time, advanced by hand with `advance()`."""

    def __init__(self, robot: SpotRobotEmulator, waypoints: dict[str, str] | None = None, steps_to_goal: int = 3) -> None:
        self.robot = robot
        self.waypoints = dict(waypoints if waypoints is not None else {"dock": "wp-1", "bench": "wp-2"})
        self.steps_to_goal = steps_to_goal
        self.navigations: list[tuple[str, float]] = []
        self._active: int | None = None
        self._remaining = 0
        self._next_id = 500
        self._stuck = False
        self._lost = False
        self._reached: set[int] = set()
        self.map_unreadable = False

    def get_stuck(self, stuck: bool = True) -> None:
        self._stuck = stuck

    # -- SpotGraphNavSink ---------------------------------------------------
    def waypoint_id_for(self, name: str) -> str | None:
        if self.map_unreadable:
            raise OSError("graph not uploaded")
        return self.waypoints.get(name)

    def navigate_to(self, waypoint_id: str, end_time_secs: float) -> int:
        if waypoint_id not in self.waypoints.values():
            raise OSError(f"unknown waypoint {waypoint_id}")
        if self.robot.estop_engaged or not self.robot.powered_on:
            raise OSError("motors are not powered on")
        if not self.robot.lease_held:
            raise OSError("LeaseUseError: lease not held by this client")
        if self.robot.posture == "SITTING":
            raise OSError("the robot must stand before it navigates")
        if end_time_secs <= time.time():
            raise OSError("the command expired before it started")
        self.navigations.append((waypoint_id, end_time_secs))
        self._next_id += 1
        self._active, self._remaining, self._lost = self._next_id, self.steps_to_goal, False
        self.robot.posture = "MOVING"
        return self._next_id

    def navigation_status(self, command_id: int) -> str:
        if command_id in self._reached:
            return "STATUS_REACHED_GOAL"
        if command_id != self._active:
            return "STATUS_UNKNOWN"
        if self._lost or self.robot.estop_engaged or not self.robot.powered_on:
            return "STATUS_LOST"
        if self._stuck:
            return "STATUS_STUCK"
        return "STATUS_FOLLOWING_ROUTE"

    # -- the world ----------------------------------------------------------
    def advance(self, ticks: int = 1) -> None:
        for _ in range(ticks):
            if self._active is None:
                return
            if self.robot.estop_engaged or not self.robot.powered_on:
                self._lost = True
                return
            if self._stuck:
                return
            self._remaining -= 1
            if self._remaining <= 0:
                self._reached.add(self._active)
                self._active = None
                self.robot.posture = "STANDING"


class SpotArmEmulator:
    """A gripper with objects that can or cannot be grasped; the grasp settles on `settle()`."""

    def __init__(self, robot: SpotRobotEmulator, graspable: set[str] | None = None) -> None:
        self.robot = robot
        self.graspable = set(graspable if graspable is not None else {"cup-3"})
        self.calls: list[tuple] = []
        self._held: str | None = None
        self._pending: str | None = None
        self._next_id = 700

    def _check_ready(self) -> None:
        if self.robot.estop_engaged or not self.robot.powered_on:
            raise OSError("motors are not powered on")
        if not self.robot.lease_held:
            raise OSError("LeaseUseError: lease not held by this client")
        if self.robot.posture != "STANDING":
            raise OSError("the arm works only while the robot stands")

    # -- SpotArmSink --------------------------------------------------------
    def holding(self) -> bool:
        return self._held is not None

    def grasp_object(self, object_id: str) -> int:
        self._check_ready()
        self.calls.append(("grasp", object_id))
        if object_id not in self.graspable:
            raise OSError(f"the grasp of {object_id} was refused: no valid grasp found")
        self._pending = object_id
        self._next_id += 1
        return self._next_id

    def place_at(self, x: float, y: float) -> int:
        self._check_ready()
        self.calls.append(("place", x, y))
        self._held = None
        self._next_id += 1
        return self._next_id

    # -- the world ----------------------------------------------------------
    def settle(self) -> None:
        """The pending grasp closes; an emergency stop in between drops the object."""
        if self._pending is None:
            return
        if self.robot.estop_engaged or not self.robot.powered_on:
            self._pending = None
            return
        self._held, self._pending = self._pending, None

    def drop_on_power_loss(self) -> None:
        if self.robot.estop_engaged or not self.robot.powered_on:
            self._held = None
