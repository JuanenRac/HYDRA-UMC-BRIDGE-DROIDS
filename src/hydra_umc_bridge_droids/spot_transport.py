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
- `RobotCommandBuilder.synchro_trajectory_command_in_body_frame(...)` for
  WALK_TO - takes a `frame_tree_snapshot` sourced from the robot's own
  live state (via `RobotStateClient`), which this module accepts as a
  caller-supplied opaque value rather than computing itself, the same
  "forward, don't interpret" boundary this whole bridge already keeps.
- `RobotCommandClient.robot_command(command, end_time_secs=...)` to
  actually send a built command.

Both the command builder and the command sink are written against small
Protocols matching bosdyn-client's own real method signatures, so the
gating/composition logic is unit-testable with plain fakes - no real Spot,
network, or bosdyn-client install required. `open_bosdyn_robot_command()`
is the one place bosdyn-client is imported, lazily.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from hydra_umc_sdk.bridge_contract import CellState, MachineState

from .coordinator import DroidCoordinator, DroidDispatch


class SpotCommandBuilder(Protocol):
    """Matches bosdyn-client's real `RobotCommandBuilder` static methods."""

    def synchro_stand_command(self) -> object: ...
    def synchro_sit_command(self) -> object: ...
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


@dataclass(frozen=True)
class SpotSendResult:
    sent: bool
    reason: str


class SpotDroidControl:
    """Build and send only the real bosdyn-client command for an already-gated dispatch."""

    def sit(self, builder: SpotCommandBuilder, sink: SpotCommandSink) -> SpotSendResult:
        # Always allowed - mirrors DroidCoordinator.sit_request()'s own
        # real de-escalation reasoning exactly, one level down at the
        # transport layer.
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
        goal_x: float,
        goal_y: float,
        goal_heading: float,
        frame_tree_snapshot: object,
    ) -> SpotSendResult:
        # A rejected dispatch (the shared SDK gate already said no) must
        # never reach the network - the transport layer is not a second
        # place to reconsider a safety decision already made.
        if not dispatch.accepted:
            return SpotSendResult(False, dispatch.reason)
        command = builder.synchro_trajectory_command_in_body_frame(goal_x, goal_y, goal_heading, frame_tree_snapshot)
        return self._send(command, sink)

    @staticmethod
    def _send(command: object, sink: SpotCommandSink) -> SpotSendResult:
        try:
            sink.robot_command(command)
        except OSError as error:
            return SpotSendResult(False, f"Spot command send failed: {error}")
        return SpotSendResult(True, "sent")
