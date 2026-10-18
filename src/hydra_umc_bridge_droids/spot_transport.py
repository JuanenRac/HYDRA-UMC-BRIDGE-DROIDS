# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - Real Boston Dynamics Spot SDK transport
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Send an already-gated DroidDispatch as a real bosdyn-client command.

Never computes gait, balance or a trajectory itself - it only builds and
sends the real bosdyn-client command objects, exactly mirroring the sibling
UAV/AMR bridges' own "send only what the SDK gate already approved" shape.

Real, documented bosdyn-client API (dev.bostondynamics.com/python/
bosdyn-client/src/bosdyn/client/robot_command), never guessed:
- `RobotCommandBuilder.synchro_stand_command()` for STAND.
- `RobotCommandBuilder.synchro_sit_command()` for SIT.
- `RobotCommandBuilder.stop_command()` for HOLD_POSITION (the ABORT action):
  the robot stops where it is.
- `RobotCommandBuilder.synchro_trajectory_command_in_body_frame(...)` for
  WALK_TO - takes a `frame_tree_snapshot` sourced from the robot's own
  live state (via `RobotStateClient`), which this module accepts as a
  caller-supplied opaque value rather than computing itself, the same
  "forward, don't interpret" boundary this whole bridge already keeps.
- `RobotCommandClient.robot_command(command, end_time_secs=...)` to
  actually send a built command. A walk always carries an `end_time_secs`: if
  this process or its network goes away, the robot's own command expires
  instead of walking on to the goal unsupervised.

What this module does NOT do yet, and a real Spot needs before it can be
commanded at all: registering a software E-stop endpoint with its keep-alive
(the dead-man that cuts the robot when this bridge dies), acquiring and
keeping the lease, and powering the motors on. `open_bosdyn_robot_command()`
only authenticates and syncs time; those steps, and RETURN_HOME / PICK_OBJECT /
PLACE_OBJECT, have no transport here. Nothing in this module has run against a
real Spot.

Both the command builder and the command sink are written against small
Protocols matching bosdyn-client's own real method signatures, so the
gating/composition logic is unit-testable with plain fakes - no real Spot,
network, or bosdyn-client install required. `open_bosdyn_robot_command()`
is the one place bosdyn-client is imported, lazily.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from hydra_umc_sdk.bridge_contract import CellState, MachineState

from .coordinator import DroidCoordinator, DroidDispatch


class SpotCommandBuilder(Protocol):
    """Matches bosdyn-client's real `RobotCommandBuilder` static methods."""

    def synchro_stand_command(self) -> object: ...
    def synchro_sit_command(self) -> object: ...
    def stop_command(self) -> object: ...
    def synchro_trajectory_command_in_body_frame(
        self, goal_x_rt_body: float, goal_y_rt_body: float, goal_heading_rt_body: float, frame_tree_snapshot: object
    ) -> object: ...


class SpotCommandSink(Protocol):
    """Matches bosdyn-client's real `RobotCommandClient.robot_command()`."""

    def robot_command(self, command: object, end_time_secs: float | None = None) -> object: ...


def open_bosdyn_robot_command(hostname: str, username: str, password: str) -> tuple[SpotCommandBuilder, SpotCommandSink]:
    """Authenticate against a real Spot and return (builder, sink).

    The only place this module imports bosdyn-client. Raises RuntimeError
    with a clear message if it isn't installed, rather than letting an
    ImportError surface from deep inside this module. Follows bosdyn-client's
    own documented bring-up sequence: create SDK, create robot, authenticate,
    wait for time sync, get the RobotCommandClient.
    """

    try:
        import bosdyn.client  # type: ignore[import-untyped]
        import bosdyn.client.util  # type: ignore[import-untyped]
        from bosdyn.client.robot_command import RobotCommandBuilder, RobotCommandClient  # type: ignore[import-untyped]
    except ImportError as error:
        raise RuntimeError(
            "bosdyn-client is not installed - install it to send real commands to a Spot robot "
            "(this module's command-building/gating logic works and is tested without it)"
        ) from error

    sdk = bosdyn.client.create_standard_sdk("hydra-umc-bridge-droids")
    robot = sdk.create_robot(hostname)
    robot.authenticate(username, password)
    robot.time_sync.wait_for_sync()
    command_client = robot.ensure_client(RobotCommandClient.default_service_name)
    return RobotCommandBuilder, command_client


# bosdyn's RobotCommandResponse.Status.STATUS_OK
_STATUS_OK = 1


def _is_finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class SpotSendResult:
    sent: bool
    reason: str


class SpotDroidControl:
    """Build and send only the real bosdyn-client command for an already-gated dispatch."""

    def hold_position(
        self, builder: SpotCommandBuilder, sink: SpotCommandSink, dispatch: DroidDispatch | None = None
    ) -> SpotSendResult:
        """Stop where the robot is: the transport of ABORT's HOLD_POSITION.

        Never gated: a stop must be reachable whatever the cell or machine says.
        A `dispatch` that is given must be a HOLD_POSITION one.
        """

        if dispatch is not None and dispatch.action != DroidCoordinator.HOLD_POSITION:
            return SpotSendResult(False, f"hold_position cannot act on a {dispatch.action} dispatch")
        return self._send(builder.stop_command(), sink)

    def sit(self, builder: SpotCommandBuilder, sink: SpotCommandSink, *, stop_first: bool = True) -> SpotSendResult:
        # Always allowed - mirrors DroidCoordinator.sit_request()'s own
        # real de-escalation reasoning exactly, one level down at the
        # transport layer. Sitting down is not instant, and a robot that is
        # walking (or carrying something) must not be told to sit mid-stride:
        # the robot is stopped first. This does not know where it stands (on
        # stairs, in a doorway): that needs its robot state, not read here.
        if stop_first:
            stopped = self.hold_position(builder, sink)
            if not stopped.sent:
                return SpotSendResult(False, f"not sitting, the robot could not be stopped first: {stopped.reason}")
        return self._send(builder.synchro_sit_command(), sink)

    def stand(
        self, builder: SpotCommandBuilder, sink: SpotCommandSink, cell_state: CellState, machine_state: MachineState
    ) -> SpotSendResult:
        # Delegates the real gate decision to DroidCoordinator.stand_request()
        # rather than re-implementing the READY+IDLE check here - a single
        # source of truth for whether standing is currently allowed.
        decision = DroidCoordinator().stand_request(cell_state, machine_state)
        if not decision.accepted:
            return SpotSendResult(False, decision.reason)
        return self._send(builder.synchro_stand_command(), sink)

    def walk_to(
        self,
        builder: SpotCommandBuilder,
        sink: SpotCommandSink,
        dispatch: DroidDispatch,
        *,
        frame_tree_snapshot: object,
        command_timeout_s: float,
        goal_heading: float = 0.0,
        max_distance_m: float | None = None,
        clock: Callable[[], float] = time.time,
    ) -> SpotSendResult:
        """Send the walk a WALK_TO dispatch was accepted for.

        The goal is the one the gate validated (`dispatch.parameters`), never a
        value passed next to it, and the dispatch must be a WALK_TO. The command
        expires `command_timeout_s` seconds from now (the robot drops it then),
        and, when `max_distance_m` is given (a profile's `max_walk_distance_m`),
        a goal farther than that is refused.
        """

        # A rejected dispatch (the shared SDK gate already said no) must
        # never reach the network - the transport layer is not a second
        # place to reconsider a safety decision already made.
        if not dispatch.accepted:
            return SpotSendResult(False, dispatch.reason)
        if dispatch.action != DroidCoordinator.WALK_TO:
            return SpotSendResult(False, f"walk_to cannot act on a {dispatch.action} dispatch")
        goal_x, goal_y = dispatch.parameters.get("x"), dispatch.parameters.get("y")
        if not all(_is_finite_number(value) for value in (goal_x, goal_y)):
            return SpotSendResult(False, "the WALK_TO dispatch carries no validated finite x and y")
        if not _is_finite_number(goal_heading):
            return SpotSendResult(False, f"goal_heading must be a finite number, got {goal_heading!r}")
        if not _is_finite_number(command_timeout_s) or command_timeout_s <= 0:
            return SpotSendResult(False, f"command_timeout_s must be a finite, positive number of seconds, got {command_timeout_s!r}")
        if max_distance_m is not None:
            if not _is_finite_number(max_distance_m) or max_distance_m <= 0:
                return SpotSendResult(False, f"max_distance_m must be a finite, positive number, got {max_distance_m!r}")
            if math.hypot(goal_x, goal_y) > max_distance_m:
                return SpotSendResult(False, f"the goal is {math.hypot(goal_x, goal_y):.1f} m away, beyond the {max_distance_m:g} m limit")
        command = builder.synchro_trajectory_command_in_body_frame(goal_x, goal_y, goal_heading, frame_tree_snapshot)
        return self._send(command, sink, end_time_secs=clock() + command_timeout_s)

    @staticmethod
    def _send(command: object, sink: SpotCommandSink, *, end_time_secs: float | None = None) -> SpotSendResult:
        try:
            result = sink.robot_command(command) if end_time_secs is None else sink.robot_command(command, end_time_secs=end_time_secs)
        except OSError as error:
            return SpotSendResult(False, f"Spot command send failed: {error}")
        except Exception as error:
            # a
            # real bosdyn-client failure (expired auth token, RPC timeout,
            # a real robot fault) raises from bosdyn's own exception
            # hierarchy (bosdyn.client.exceptions.Error), not OSError - it
            # used to propagate uncaught here instead of degrading to a
            # clean SpotSendResult like every other transport failure in
            # this bridge family already does. Narrowed to that real
            # hierarchy specifically (imported lazily, same reasoning as
            # open_bosdyn_robot_command() above) so a genuine bug in this
            # module's own code - or in a test's fake sink, which never
            # raises a real bosdyn error - still surfaces as an unhandled
            # exception instead of being silently downgraded.
            try:
                from bosdyn.client.exceptions import Error as BosdynError
            except ImportError:
                # bosdyn-client isn't installed, so `error` cannot be a
                # real bosdyn error - re-raise the ORIGINAL exception, not
                # this ImportError (a bare `raise` here would re-raise the
                # ImportError instead and mask the real failure).
                raise error from None
            if not isinstance(error, BosdynError):
                raise
            return SpotSendResult(False, f"Spot command send failed: {error}")
        # The real client raises for a command the robot cannot run and returns an id; a client
        # that answers with a response object instead (a status field) is not trusted to mean "ok".
        status = getattr(result, "status", None)
        if status is not None and status != _STATUS_OK:
            return SpotSendResult(False, f"Spot did not accept the command (status {status!r})")
        return SpotSendResult(True, "sent")
