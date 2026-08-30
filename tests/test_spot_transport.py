# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - Real Spot SDK transport tests
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Tests SpotDroidControl against fake builder/sink objects.

No real Spot, network, or bosdyn-client install is needed:
SpotDroidControl is written against the small SpotCommandBuilder/
SpotCommandSink protocols (matching bosdyn-client's own real
RobotCommandBuilder/RobotCommandClient method signatures), so plain fakes
prove the gating/composition logic is correct independent of bosdyn-client
- only open_bosdyn_robot_command() itself needs it, and it isn't exercised
here.
"""

import unittest

from hydra_umc_sdk.bridge_contract import CellState, MachineState
from hydra_umc_bridge_droids import DroidDispatch, SpotDroidControl


class FakeBuilder:
    def __init__(self):
        self.calls: list[tuple] = []

    def synchro_stand_command(self):
        self.calls.append(("stand",))
        return "STAND_COMMAND"

    def synchro_sit_command(self):
        self.calls.append(("sit",))
        return "SIT_COMMAND"

    def synchro_trajectory_command_in_body_frame(self, goal_x_rt_body, goal_y_rt_body, goal_heading_rt_body, frame_tree_snapshot):
        self.calls.append(("trajectory", goal_x_rt_body, goal_y_rt_body, goal_heading_rt_body, frame_tree_snapshot))
        return "TRAJECTORY_COMMAND"


class FakeSink:
    def __init__(self):
        self.sent: list[object] = []
        self.raise_on_send: OSError | None = None

    def robot_command(self, command, end_time_secs=None):
        if self.raise_on_send:
            raise self.raise_on_send
        self.sent.append(command)


class SpotDroidControlTests(unittest.TestCase):
    def setUp(self):
        self.builder = FakeBuilder()
        self.sink = FakeSink()
        self.control = SpotDroidControl()

    def test_sit_is_always_allowed_and_sends_the_real_command(self):
        result = self.control.sit(self.builder, self.sink)
        self.assertTrue(result.sent)
        self.assertEqual(self.builder.calls, [("sit",)])
        self.assertEqual(self.sink.sent, ["SIT_COMMAND"])

    def test_stand_requires_a_ready_cell_and_idle_machine_before_any_send(self):
        rejected = self.control.stand(self.builder, self.sink, CellState.INHIBITED, MachineState.IDLE)
        self.assertFalse(rejected.sent)
        self.assertEqual(self.builder.calls, [])
        self.assertEqual(self.sink.sent, [])

        accepted = self.control.stand(self.builder, self.sink, CellState.READY, MachineState.IDLE)
        self.assertTrue(accepted.sent)
        self.assertEqual(self.sink.sent, ["STAND_COMMAND"])

    def test_walk_to_rejected_dispatch_is_never_built_or_sent(self):
        rejected = DroidDispatch(False, "WALK_TO", "cell is FAULT, not READY")
        result = self.control.walk_to(self.builder, self.sink, rejected, 1.0, 2.0, 0.0, frame_tree_snapshot=None)
        self.assertFalse(result.sent)
        self.assertEqual(self.builder.calls, [])
        self.assertEqual(self.sink.sent, [])

    def test_walk_to_accepted_dispatch_builds_the_real_trajectory_command(self):
        accepted = DroidDispatch(True, "WALK_TO", "cell and external machine are ready")
        snapshot = object()
        result = self.control.walk_to(self.builder, self.sink, accepted, 1.5, -2.5, 0.3, frame_tree_snapshot=snapshot)
        self.assertTrue(result.sent)
        self.assertEqual(self.builder.calls, [("trajectory", 1.5, -2.5, 0.3, snapshot)])
        self.assertEqual(self.sink.sent, ["TRAJECTORY_COMMAND"])

    def test_a_transport_failure_is_reported_not_swallowed(self):
        self.sink.raise_on_send = OSError("robot unreachable")
        result = self.control.sit(self.builder, self.sink)
        self.assertFalse(result.sent)
        self.assertIn("robot unreachable", result.reason)


class OpenBosdynRobotCommandTests(unittest.TestCase):
    def test_missing_bosdyn_client_raises_a_clear_runtime_error_not_an_import_error(self):
        from hydra_umc_bridge_droids import open_bosdyn_robot_command

        try:
            import bosdyn.client  # noqa: F401

            self.skipTest("bosdyn-client is installed in this environment - nothing to prove here")
        except ImportError:
            pass
        with self.assertRaises(RuntimeError) as context:
            open_bosdyn_robot_command("192.168.80.3", "user", "password")
        self.assertIn("bosdyn-client is not installed", str(context.exception))


if __name__ == "__main__":
    unittest.main()
