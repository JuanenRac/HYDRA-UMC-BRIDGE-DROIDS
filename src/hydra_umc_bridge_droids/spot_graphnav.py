# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - Spot GraphNav: named waypoints of the recorded map
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Go to a named waypoint of the robot's recorded map instead of a coordinate.

WALK_TO and RETURN_HOME can name a waypoint of the GraphNav map (the annotation name given
when the map was recorded). The bridge never plans a path: it asks the robot for the id of the
waypoint, refuses an unknown name, and sends one navigate-to command that expires on its own
(`command_timeout_s`), exactly like `SpotDroidControl.walk_to`. Only a dispatch the gate accepted
is acted on. The shape of the sink is that of bosdyn-client's `GraphNavClient`
(`navigate_to(destination_waypoint_id, destination_waypoint_tform_body_goal, command_id)`,
`navigation_feedback(command_id)`), reached through three small methods so the logic is tested
with a fake map. Nothing here has run against a real Spot.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from .coordinator import DroidCoordinator, DroidDispatch
from .spot_session import SpotSessionConfig


class SpotGraphNavSink(Protocol):
    def waypoint_id_for(self, name: str) -> str | None: ...
    def navigate_to(self, waypoint_id: str, end_time_secs: float) -> int: ...
    def navigation_status(self, command_id: int) -> str: ...


@dataclass(frozen=True)
class GraphNavResult:
    sent: bool
    reason: str
    command_id: int | None = None
    waypoint_id: str | None = None


class SpotGraphNav:
    def __init__(self, config: SpotSessionConfig | None = None) -> None:
        self.config = config or SpotSessionConfig()

    def go_to_waypoint(
        self,
        sink: SpotGraphNavSink,
        dispatch: DroidDispatch,
        waypoint_name: str,
        *,
        command_timeout_s: float,
        clock: Callable[[], float] = time.time,
    ) -> GraphNavResult:
        """WALK_TO towards a named waypoint (the x and y of the dispatch stay validated but unused)."""

        if not dispatch.accepted:
            return GraphNavResult(False, dispatch.reason)
        if dispatch.action != DroidCoordinator.WALK_TO:
            return GraphNavResult(False, f"go_to_waypoint cannot act on a {dispatch.action} dispatch")
        return self._navigate(sink, waypoint_name, command_timeout_s, clock)

    def return_home(
        self, sink: SpotGraphNavSink, dispatch: DroidDispatch, *, command_timeout_s: float, clock: Callable[[], float] = time.time
    ) -> GraphNavResult:
        """RETURN_HOME towards the home waypoint named in the session configuration."""

        if not dispatch.accepted:
            return GraphNavResult(False, dispatch.reason)
        if dispatch.action != DroidCoordinator.RETURN_HOME:
            return GraphNavResult(False, f"return_home cannot act on a {dispatch.action} dispatch")
        return self._navigate(sink, self.config.home_waypoint, command_timeout_s, clock)

    @staticmethod
    def _navigate(sink: SpotGraphNavSink, name: str, command_timeout_s: float, clock: Callable[[], float]) -> GraphNavResult:
        if not isinstance(name, str) or not name.strip():
            return GraphNavResult(False, "a waypoint name is needed")
        if (
            not isinstance(command_timeout_s, (int, float))
            or isinstance(command_timeout_s, bool)
            or not math.isfinite(command_timeout_s)
            or command_timeout_s <= 0
        ):
            return GraphNavResult(False, f"command_timeout_s must be a finite, positive number of seconds, got {command_timeout_s!r}")
        try:
            waypoint_id = sink.waypoint_id_for(name.strip())
        except Exception as error:
            return GraphNavResult(False, f"the map could not be read: {error}")
        if not waypoint_id:
            return GraphNavResult(False, f"the map has no waypoint named {name.strip()!r}")
        try:
            command_id = sink.navigate_to(waypoint_id, clock() + command_timeout_s)
        except Exception as error:
            return GraphNavResult(False, f"Spot navigation failed: {error}", waypoint_id=waypoint_id)
        return GraphNavResult(True, "sent", command_id, waypoint_id)

    @staticmethod
    def reached(sink: SpotGraphNavSink, result: GraphNavResult) -> bool:
        """True when the robot reports it reached the waypoint of an earlier `sent` result."""

        if not result.sent or result.command_id is None:
            return False
        try:
            return sink.navigation_status(result.command_id) == "STATUS_REACHED_GOAL"
        except Exception:
            return False
