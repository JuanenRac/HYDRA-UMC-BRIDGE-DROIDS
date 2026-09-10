# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - Bridge <-> realistic Spot emulator tests
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Run this bridge's REAL SpotDroidControl end to end against a
bosdyn-client-shaped Spot: real RobotCommand proto shapes, a real
RobotCommandResponse.Status enum, and a real posture/motion state machine
polled with robot_command_feedback - not a record-only FakeSink.
"""
from __future__ import annotations

import time
import unittest

from hydra_umc_bridge_droids import DroidDispatch, SpotDroidControl
from hydra_umc_sdk.bridge_contract import CellState, MachineState

from spot_emulator import (
    SpotCommandBuilderEmulator,
    SpotRobotEmulator,
    STATUS_OK,
    STATUS_NOT_POWERED_ON,
    STATUS_BEHAVIOR_FAULT,
    STATUS_EXPIRED,
    STATUS_TOO_DISTANT,
    TRAJ_STATUS_AT_GOAL,
    TRAJ_STATUS_GOING_TO_GOAL,
)


def _walk() -> DroidDispatch:
    return DroidDispatch(True, "WALK_TO", "cell and external machine are ready")


class BridgeAgainstSpotRobotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = SpotCommandBuilderEmulator()
        self.spot = SpotRobotEmulator()
        self.control = SpotDroidControl()

    def test_stand_from_a_ready_idle_cell_actually_stands_the_robot(self) -> None:
        result = self.control.stand(self.builder, self.spot, CellState.READY, MachineState.IDLE)
        self.assertTrue(result.sent, result.reason)
        self.assertEqual(self.spot.last_status, STATUS_OK)
        self.assertEqual(self.spot.posture, "STANDING")

    def test_a_full_stand_walk_arrive_sit_lifecycle_over_real_proto_commands(self) -> None:
        self.control.stand(self.builder, self.spot, CellState.READY, MachineState.IDLE)
        result = self.control.walk_to(self.builder, self.spot, _walk(), 3.0, -1.0, 0.2, frame_tree_snapshot=object())
        self.assertTrue(result.sent, result.reason)
        self.assertEqual(self.spot.last_status, STATUS_OK)
        self.assertEqual(self.spot.posture, "MOVING")

        # The last command the bridge sent is a real se2_trajectory_request.
        mobility = self.spot.commands[-1]["synchronized_command"]["mobility_command"]
        self.assertIn("se2_trajectory_request", mobility)
        point = mobility["se2_trajectory_request"]["trajectory"]["points"][0]["pose"]
        self.assertEqual((point["x"], point["y"], point["angle"]), (3.0, -1.0, 0.2))

        traj_id = self.spot.responses[-1].command_id
        self.assertEqual(self.spot.robot_command_feedback(traj_id).se2_trajectory_feedback_status, TRAJ_STATUS_GOING_TO_GOAL)
        self.spot.step()  # arrives
        self.assertEqual(self.spot.robot_command_feedback(traj_id).se2_trajectory_feedback_status, TRAJ_STATUS_AT_GOAL)
        self.assertEqual(self.spot.posture, "STANDING")

        self.control.sit(self.builder, self.spot)
        self.assertEqual(self.spot.posture, "SITTING")

    def test_walking_from_a_sit_comes_back_as_a_behavior_fault_status(self) -> None:
        # The robot is SITTING - a real Spot refuses to walk without standing first.
        result = self.control.walk_to(self.builder, self.spot, _walk(), 1.0, 1.0, 0.0, frame_tree_snapshot=object())
        # The bridge honestly reports "sent" (the command left this process);
        # the robot's own response carries the real refusal.
        self.assertTrue(result.sent)
        self.assertEqual(self.spot.last_status, STATUS_BEHAVIOR_FAULT)
        self.assertEqual(self.spot.posture, "SITTING")

    def test_an_engaged_estop_makes_every_motion_command_come_back_not_powered_on(self) -> None:
        self.control.stand(self.builder, self.spot, CellState.READY, MachineState.IDLE)
        self.spot.engage_estop()
        self.control.stand(self.builder, self.spot, CellState.READY, MachineState.IDLE)
        self.assertEqual(self.spot.last_status, STATUS_NOT_POWERED_ON)
        self.assertEqual(self.spot.emit_robot_state()["power_state"]["motor_power_state"], "STATE_ESTOPPED")

    def test_sit_is_still_accepted_while_powered_after_a_behavior_fault(self) -> None:
        self.control.stand(self.builder, self.spot, CellState.READY, MachineState.IDLE)
        self.spot.raise_behavior_fault()
        # STAND now faults...
        self.control.stand(self.builder, self.spot, CellState.READY, MachineState.IDLE)
        self.assertEqual(self.spot.last_status, STATUS_BEHAVIOR_FAULT)
        # ...but SIT (de-escalation) is still accepted.
        self.control.sit(self.builder, self.spot)
        self.assertEqual(self.spot.last_status, STATUS_OK)
        self.assertEqual(self.spot.posture, "SITTING")

    def test_a_goal_beyond_the_body_frame_limit_comes_back_too_distant(self) -> None:
        self.control.stand(self.builder, self.spot, CellState.READY, MachineState.IDLE)
        self.control.walk_to(self.builder, self.spot, _walk(), 60.0, 0.0, 0.0, frame_tree_snapshot=object())
        self.assertEqual(self.spot.last_status, STATUS_TOO_DISTANT)
        self.assertEqual(self.spot.posture, "STANDING")

    def test_a_lease_lost_mid_rpc_degrades_cleanly_not_an_uncaught_exception(self) -> None:
        self.spot.set_lease_held(False)
        result = self.control.stand(self.builder, self.spot, CellState.READY, MachineState.IDLE)
        self.assertFalse(result.sent)
        self.assertIn("LeaseUseError", result.reason)

    def test_a_dispatch_the_shared_gate_already_rejected_never_reaches_the_robot(self) -> None:
        rejected = DroidDispatch(False, "WALK_TO", "cell is FAULT, not READY")
        result = self.control.walk_to(self.builder, self.spot, rejected, 1.0, 2.0, 0.0, frame_tree_snapshot=None)
        self.assertFalse(result.sent)
        self.assertEqual(self.spot.commands, [])

    def test_a_trajectory_end_time_already_in_the_past_comes_back_expired(self) -> None:
        self.control.stand(self.builder, self.spot, CellState.READY, MachineState.IDLE)
        command = self.builder.synchro_trajectory_command_in_body_frame(1.0, 1.0, 0.0, object())
        self.spot.robot_command(command, end_time_secs=time.time() - 5)
        self.assertEqual(self.spot.last_status, STATUS_EXPIRED)


if __name__ == "__main__":
    unittest.main()
