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
    patched_bosdyn_exceptions,
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


def _walk(x: float = 1.0, y: float = 1.0) -> DroidDispatch:
    return DroidDispatch(True, "WALK_TO", "cell and external machine are ready", parameters={"x": x, "y": y})


class BridgeAgainstSpotRobotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = SpotCommandBuilderEmulator()
        self.spot = SpotRobotEmulator()
        self.control = SpotDroidControl()
        bosdyn_errors = patched_bosdyn_exceptions()
        bosdyn_errors.__enter__()
        self.addCleanup(bosdyn_errors.__exit__, None, None, None)

    def _walk_to(self, x, y, heading=0.0, dispatch=None):
        return self.control.walk_to(
            self.builder, self.spot, dispatch or _walk(x, y), frame_tree_snapshot=object(), command_timeout_s=30.0, goal_heading=heading
        )

    def test_stand_from_a_ready_idle_cell_actually_stands_the_robot(self) -> None:
        result = self.control.stand(self.builder, self.spot, CellState.READY, MachineState.IDLE)
        self.assertTrue(result.sent, result.reason)
        self.assertEqual(self.spot.last_status, STATUS_OK)
        self.assertEqual(self.spot.posture, "STANDING")

    def test_a_full_stand_walk_arrive_sit_lifecycle_over_real_proto_commands(self) -> None:
        self.control.stand(self.builder, self.spot, CellState.READY, MachineState.IDLE)
        result = self._walk_to(3.0, -1.0, 0.2)
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

    def test_walking_from_a_sit_is_reported_as_not_sent_with_the_robots_own_refusal(self) -> None:
        # The robot is SITTING - a real Spot refuses to walk without standing first,
        # and the real client raises for it: that is a failed send, never a "sent".
        result = self._walk_to(1.0, 1.0)
        self.assertFalse(result.sent)
        self.assertIn("status 9", result.reason)
        self.assertEqual(self.spot.last_status, STATUS_BEHAVIOR_FAULT)
        self.assertEqual(self.spot.posture, "SITTING")


    def test_an_engaged_estop_makes_every_motion_command_come_back_not_powered_on(self) -> None:
        self.control.stand(self.builder, self.spot, CellState.READY, MachineState.IDLE)
        self.spot.engage_estop()
        refused = self.control.stand(self.builder, self.spot, CellState.READY, MachineState.IDLE)
        self.assertFalse(refused.sent)
        self.assertEqual(self.spot.last_status, STATUS_NOT_POWERED_ON)
        self.assertEqual(self.spot.emit_robot_state()["power_state"]["motor_power_state"], "STATE_ESTOPPED")

    def test_sit_is_still_accepted_while_powered_after_a_behavior_fault(self) -> None:
        self.control.stand(self.builder, self.spot, CellState.READY, MachineState.IDLE)
        self.spot.raise_behavior_fault()
        # STAND now faults...
        self.assertFalse(self.control.stand(self.builder, self.spot, CellState.READY, MachineState.IDLE).sent)
        self.assertEqual(self.spot.last_status, STATUS_BEHAVIOR_FAULT)
        # ...but SIT (de-escalation) is still accepted.
        self.assertTrue(self.control.sit(self.builder, self.spot).sent)
        self.assertEqual(self.spot.last_status, STATUS_OK)
        self.assertEqual(self.spot.posture, "SITTING")

    def test_a_goal_beyond_the_body_frame_limit_comes_back_too_distant(self) -> None:
        self.control.stand(self.builder, self.spot, CellState.READY, MachineState.IDLE)
        self.assertFalse(self._walk_to(60.0, 0.0).sent)
        self.assertEqual(self.spot.last_status, STATUS_TOO_DISTANT)
        self.assertEqual(self.spot.posture, "STANDING")

    def test_a_lease_lost_mid_rpc_degrades_cleanly_not_an_uncaught_exception(self) -> None:
        self.spot.set_lease_held(False)
        result = self.control.stand(self.builder, self.spot, CellState.READY, MachineState.IDLE)
        self.assertFalse(result.sent)
        self.assertIn("LeaseUseError", result.reason)

    def test_a_dispatch_the_shared_gate_already_rejected_never_reaches_the_robot(self) -> None:
        rejected = DroidDispatch(False, "WALK_TO", "cell is FAULT, not READY")
        result = self._walk_to(1.0, 2.0, dispatch=rejected)
        self.assertFalse(result.sent)
        self.assertEqual(self.spot.commands, [])

    def test_a_trajectory_end_time_already_in_the_past_comes_back_expired(self) -> None:
        self.control.stand(self.builder, self.spot, CellState.READY, MachineState.IDLE)
        command = self.builder.synchro_trajectory_command_in_body_frame(1.0, 1.0, 0.0, object())
        with self.assertRaises(Exception):
            self.spot.robot_command(command, end_time_secs=time.time() - 5)
        self.assertEqual(self.spot.last_status, STATUS_EXPIRED)

    def test_the_walk_carries_an_end_time_so_the_robot_drops_it_when_the_bridge_goes_away(self) -> None:
        self.control.stand(self.builder, self.spot, CellState.READY, MachineState.IDLE)
        seen = []
        original = self.spot.robot_command
        self.spot.robot_command = lambda command, end_time_secs=None: (seen.append(end_time_secs), original(command, end_time_secs))[1]
        before = time.time()
        self.assertTrue(self._walk_to(1.0, 1.0).sent)
        self.assertGreater(seen[0], before + 29.0)
        self.assertLess(seen[0], time.time() + 31.0)

    def test_hold_position_stops_a_walking_robot_where_it_is(self) -> None:
        self.control.stand(self.builder, self.spot, CellState.READY, MachineState.IDLE)
        self.assertTrue(self._walk_to(5.0, 0.0).sent)
        self.assertEqual(self.spot.posture, "MOVING")
        # ABORT -> HOLD_POSITION: the stop reaches the robot and the goal is dropped.
        hold = DroidDispatch(True, "HOLD_POSITION", "abort requests are always forwarded to the authorised safety path")
        self.assertTrue(self.control.hold_position(self.builder, self.spot, hold).sent)
        self.assertEqual(self.spot.posture, "STANDING")
        self.assertIsNone(self.spot.goal_body)

    def test_sit_stops_a_walking_robot_before_sitting_it_down(self) -> None:
        self.control.stand(self.builder, self.spot, CellState.READY, MachineState.IDLE)
        self._walk_to(5.0, 0.0)
        self.assertTrue(self.control.sit(self.builder, self.spot).sent)
        kinds = [next(iter(c.get("full_body_command") or c["synchronized_command"]["mobility_command"])) for c in self.spot.commands[-2:]]
        self.assertEqual(kinds, ["stop_request", "sit_request"])
        self.assertEqual(self.spot.posture, "SITTING")

    def test_a_robot_that_answers_with_a_response_object_that_is_not_ok_is_not_a_sent(self) -> None:
        class Sink:
            def robot_command(self, command, end_time_secs=None):
                return type("Response", (), {"status": 7})()

        self.assertFalse(self.control.hold_position(self.builder, Sink()).sent)


if __name__ == "__main__":
    unittest.main()
