# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - Realistic Boston Dynamics Spot emulator (fixture)
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""A bosdyn-client-shaped Spot on the exact `SpotCommandBuilder` /
`SpotCommandSink` seams this bridge's real `spot_transport.py` talks to.

Until now the only doubles here were `FakeBuilder` (returns opaque
sentinels) and `FakeSink` (records one call, or raises). A real Spot's
`RobotCommandClient.robot_command()`:

  * accepts a real `RobotCommand` protobuf whose
    `synchronized_command.mobility_command` carries exactly one of a
    `stand_request` / `sit_request` / `se2_trajectory_request`;
  * answers a command it accepts with an integer command id, and turns any
    other `RobotCommandResponse.Status` (`STATUS_NOT_POWERED_ON`,
    `STATUS_EXPIRED`, `STATUS_TOO_DISTANT`, `STATUS_BEHAVIOR_FAULT`, ...)
    into an exception of bosdyn's own hierarchy (`NotPoweredOnError`,
    `ExpiredError`, `TooDistantError`, `BehaviorFaultError`, ...) - this
    emulator does the same, with `EmulatorBosdynError` as the base class a
    test installs as `bosdyn.client.exceptions.Error` (see
    `patched_bosdyn_exceptions()`); `responses` / `last_status` keep what each
    command was answered with;
  * moves the robot through a real posture/motion state machine that a
    caller then polls with `robot_command_feedback(command_id)`.

`SpotCommandBuilderEmulator` builds real-proto-shaped command objects;
`SpotRobotEmulator` (the sink) executes them against that state machine.
`engage_estop()`, `set_lease_held()`, `power_off()` and `set_battery()`
drive the physical side; `emit_robot_state()` returns a real-shape
`RobotState`. A lost lease is raised as `OSError`, which
`SpotDroidControl._send()` degrades cleanly, exactly like the sibling
UAV/AMR bridges.
"""

from __future__ import annotations

import math
import sys
import time
import types
from contextlib import contextmanager
from unittest import mock

# --- RobotCommandResponse.Status (real bosdyn enum values) --------------
STATUS_UNKNOWN = 0
STATUS_OK = 1
STATUS_INVALID_REQUEST = 2
STATUS_UNSUPPORTED = 3
STATUS_NO_TIMESYNC = 4
STATUS_EXPIRED = 5
STATUS_TOO_DISTANT = 6
STATUS_NOT_POWERED_ON = 7
STATUS_BEHAVIOR_FAULT = 9

# --- se2_trajectory feedback status (real bosdyn enum) ------------------
TRAJ_STATUS_UNKNOWN = 0
TRAJ_STATUS_AT_GOAL = 1
TRAJ_STATUS_GOING_TO_GOAL = 3

_MAX_TRAJECTORY_DISTANCE_M = 50.0  # real Spot rejects a body-frame goal past ~50 m


class EmulatorBosdynError(Exception):
    """Stands for `bosdyn.client.exceptions.Error`, the base of every error the real client raises."""


class NotPoweredOnError(EmulatorBosdynError):
    pass


class ExpiredError(EmulatorBosdynError):
    pass


class TooDistantError(EmulatorBosdynError):
    pass


class BehaviorFaultError(EmulatorBosdynError):
    pass


class CommandRejectedError(EmulatorBosdynError):
    """Any other status that is not STATUS_OK."""


_ERRORS_BY_STATUS = {
    STATUS_NOT_POWERED_ON: NotPoweredOnError,
    STATUS_EXPIRED: ExpiredError,
    STATUS_TOO_DISTANT: TooDistantError,
    STATUS_BEHAVIOR_FAULT: BehaviorFaultError,
}


@contextmanager
def patched_bosdyn_exceptions():
    """Install the emulator's error base as `bosdyn.client.exceptions.Error` for the length of a test."""
    exceptions = types.ModuleType("bosdyn.client.exceptions")
    exceptions.Error = EmulatorBosdynError
    modules = {
        "bosdyn": types.ModuleType("bosdyn"),
        "bosdyn.client": types.ModuleType("bosdyn.client"),
        "bosdyn.client.exceptions": exceptions,
    }
    with mock.patch.dict(sys.modules, modules):
        yield


class SpotCommandBuilderEmulator:
    """Mirrors bosdyn-client's `RobotCommandBuilder` static methods, but
    returns a real-proto-shaped `dict` the sink below can dispatch on."""

    @staticmethod
    def synchro_stand_command() -> dict:
        return {"synchronized_command": {"mobility_command": {"stand_request": {}}}}

    @staticmethod
    def synchro_sit_command() -> dict:
        return {"synchronized_command": {"mobility_command": {"sit_request": {}}}}

    @staticmethod
    def stop_command() -> dict:
        return {"full_body_command": {"stop_request": {}}}

    @staticmethod
    def synchro_trajectory_command_in_body_frame(
        goal_x_rt_body: float, goal_y_rt_body: float, goal_heading_rt_body: float, frame_tree_snapshot: object
    ) -> dict:
        return {
            "synchronized_command": {
                "mobility_command": {
                    "se2_trajectory_request": {
                        "se2_frame_name": "body",
                        "trajectory": {
                            "points": [
                                {"pose": {"x": goal_x_rt_body, "y": goal_y_rt_body, "angle": goal_heading_rt_body}}
                            ]
                        },
                        "frame_tree_snapshot": frame_tree_snapshot,
                    }
                }
            }
        }


class _CommandResponse:
    """Mirrors bosdyn `RobotCommandResponse` - only `.status` / `.command_id`
    are read by anything."""

    def __init__(self, status: int, command_id: int) -> None:
        self.status = status
        self.command_id = command_id


class _TrajectoryFeedback:
    def __init__(self, status: int) -> None:
        self.se2_trajectory_feedback_status = status


class SpotRobotEmulator:
    """A `SpotCommandSink` Spot robot with a real posture/motion state machine."""

    def __init__(self) -> None:
        self.posture = "SITTING"        # POWERED_OFF | SITTING | STANDING | MOVING
        self.powered_on = True
        self.estop_engaged = False
        self.lease_held = True
        self.battery_pct = 74.0
        self.behavior_fault = False
        self.goal_body: tuple[float, float, float] | None = None
        self._next_command_id = 100
        self.commands: list[dict] = []
        self.responses: list[_CommandResponse] = []
        self._active_traj_id: int | None = None

    # ---- physical-side drivers ----------------------------------------
    def engage_estop(self, engaged: bool = True) -> None:
        self.estop_engaged = engaged
        if engaged:
            self.powered_on = False  # a real E-stop cuts motor power
            self.posture = "POWERED_OFF"
            self.goal_body = None

    def set_lease_held(self, held: bool) -> None:
        self.lease_held = held

    def power_off(self) -> None:
        self.powered_on = False
        self.posture = "POWERED_OFF"

    def set_battery(self, pct: float) -> None:
        self.battery_pct = pct

    def raise_behavior_fault(self, faulted: bool = True) -> None:
        self.behavior_fault = faulted

    def step(self) -> None:
        """Advance one motion tick: MOVING -> arrives at goal -> STANDING."""
        if self.posture == "MOVING" and self.goal_body is not None:
            self.goal_body = None
            self.posture = "STANDING"
            if self._active_traj_id is not None:
                self._active_traj_id = None

    # ---- SpotCommandSink --------------------------------------------------
    def robot_command(self, command: object, end_time_secs: float | None = None) -> object:
        self.commands.append(command if isinstance(command, dict) else {"opaque": command})

        # Real RPC/lease failures -> raise (OSError degrades cleanly in
        # SpotDroidControl._send, same as the sibling bridges).
        if not self.lease_held:
            raise OSError("LeaseUseError: lease not held by this client")

        if not isinstance(command, dict):
            return self._respond(STATUS_INVALID_REQUEST)
        if "stop_request" in command.get("full_body_command", {}):
            # A stop is accepted whenever the motors are on, wherever the robot is going.
            if not self.powered_on:
                return self._respond(STATUS_NOT_POWERED_ON)
            self.goal_body = None
            self._active_traj_id = None
            if self.posture == "MOVING":
                self.posture = "STANDING"
            return self._respond(STATUS_OK)
        mobility = command.get("synchronized_command", {}).get("mobility_command", {})

        if "sit_request" in mobility:
            # SIT is always accepted while powered (de-escalation), even
            # after a behavior fault clears it.
            if not self.powered_on:
                return self._respond(STATUS_NOT_POWERED_ON)
            self.posture = "SITTING"
            self.goal_body = None
            return self._respond(STATUS_OK)

        if "stand_request" in mobility:
            if self.estop_engaged or not self.powered_on:
                return self._respond(STATUS_NOT_POWERED_ON)
            if self.behavior_fault:
                return self._respond(STATUS_BEHAVIOR_FAULT)
            self.posture = "STANDING"
            return self._respond(STATUS_OK)

        if "se2_trajectory_request" in mobility:
            if self.estop_engaged or not self.powered_on:
                return self._respond(STATUS_NOT_POWERED_ON)
            if self.posture == "SITTING":
                # A real Spot will not walk from a sit - it must stand first.
                return self._respond(STATUS_BEHAVIOR_FAULT)
            if end_time_secs is not None and end_time_secs <= time.time():
                return self._respond(STATUS_EXPIRED)
            request = mobility["se2_trajectory_request"]
            point = request["trajectory"]["points"][0]["pose"]
            distance = math.hypot(point["x"], point["y"])
            if distance > _MAX_TRAJECTORY_DISTANCE_M:
                return self._respond(STATUS_TOO_DISTANT)
            self.goal_body = (point["x"], point["y"], point["angle"])
            self.posture = "MOVING"
            command_id = self._respond(STATUS_OK)
            self._active_traj_id = command_id
            return command_id

        return self._respond(STATUS_UNSUPPORTED)

    def robot_command_feedback(self, command_id: int) -> object:
        if command_id == self._active_traj_id and self.posture == "MOVING":
            return _TrajectoryFeedback(TRAJ_STATUS_GOING_TO_GOAL)
        return _TrajectoryFeedback(TRAJ_STATUS_AT_GOAL)

    def _respond(self, status: int) -> int:
        """The id of an accepted command; raises, like the real client, for any other status."""
        self._next_command_id += 1
        response = _CommandResponse(status, self._next_command_id)
        self.responses.append(response)
        if status != STATUS_OK:
            raise _ERRORS_BY_STATUS.get(status, CommandRejectedError)(f"command {self._next_command_id} answered with status {status}")
        return self._next_command_id

    @property
    def last_status(self) -> int:
        return self.responses[-1].status

    # ---- RobotState ------------------------------------------------
    def emit_robot_state(self) -> dict:
        if self.estop_engaged:
            power_state = "STATE_ESTOPPED"
        elif self.powered_on:
            power_state = "STATE_ON"
        else:
            power_state = "STATE_OFF"
        return {
            "power_state": {"motor_power_state": power_state},
            "battery_states": [{"charge_percentage": self.battery_pct, "status": "STATUS_DISCHARGING"}],
            "kinematic_state": {"posture": self.posture, "goal_rt_body": self.goal_body},
            "behavior_fault_state": {"faults": ([{"status": "STATUS_CAUTION"}] if self.behavior_fault else [])},
        }
