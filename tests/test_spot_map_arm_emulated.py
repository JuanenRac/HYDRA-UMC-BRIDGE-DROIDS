# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - GraphNav and arm scenarios against the emulated Spot
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Navigation to a named waypoint and pick and place, with the emergency stop and the global stop cutting them half-way (evidence: simulator)."""

import time
import unittest

from hydra_umc_bridge_droids import DroidDispatch, SpotArmControl, SpotGraphNav, SpotSessionConfig
from hydra_umc_bridge_droids.mqtt_transport import DroidMqttBridge
from hydra_umc_bridge_droids import DroidCoordinator
from hydra_umc_sdk.bridge_contract import CellState
from hydra_umc_sdk.global_stop import GlobalStopGuard, GlobalStopSettings

from spot_emulator import SpotRobotEmulator
from spot_map_arm_emulator import SpotArmEmulator, SpotMapEmulator
from test_spot_session import FakeEstop, FakeLease, FakePower, FakeState, Clock
from hydra_umc_bridge_droids import SpotSession


def accepted(action, **parameters):
    return DroidDispatch(True, action, "ok", parameters=parameters)


class CuttingEstop(FakeEstop):
    """An emergency stop endpoint whose cut engages the emulated robot's stop, as the robot's own timeout does."""

    def __init__(self, robot):
        super().__init__()
        self.robot = robot

    def cut(self):
        super().cut()
        self.robot.engage_estop(True)


def standing_robot():
    robot = SpotRobotEmulator()
    robot.posture = "STANDING"
    return robot


class GraphNavScenarioTests(unittest.TestCase):
    def test_walk_to_a_waypoint_until_it_is_reached(self):
        robot = standing_robot()
        nav_map, nav = SpotMapEmulator(robot, steps_to_goal=3), SpotGraphNav()
        result = nav.go_to_waypoint(nav_map, accepted("WALK_TO", x=0.0, y=0.0), "bench", command_timeout_s=30)
        self.assertTrue(result.sent)
        self.assertEqual(robot.posture, "MOVING")
        self.assertFalse(nav.reached(nav_map, result))
        nav_map.advance(2)
        self.assertFalse(nav.reached(nav_map, result))
        nav_map.advance(1)
        self.assertTrue(nav.reached(nav_map, result))
        self.assertEqual(robot.posture, "STANDING")

    def test_return_home_walks_to_the_configured_waypoint(self):
        robot = standing_robot()
        nav_map = SpotMapEmulator(robot)
        result = SpotGraphNav(SpotSessionConfig(home_waypoint="dock")).return_home(nav_map, accepted("RETURN_HOME"), command_timeout_s=30)
        self.assertEqual((result.sent, result.waypoint_id), (True, "wp-1"))
        self.assertEqual(nav_map.navigations[0][0], "wp-1")

    def test_the_emergency_stop_in_the_middle_of_the_route_loses_the_navigation(self):
        robot = standing_robot()
        nav_map, nav = SpotMapEmulator(robot, steps_to_goal=5), SpotGraphNav()
        result = nav.go_to_waypoint(nav_map, accepted("WALK_TO", x=0.0, y=0.0), "bench", command_timeout_s=30)
        nav_map.advance(2)
        robot.engage_estop(True)
        nav_map.advance(3)
        self.assertEqual(nav_map.navigation_status(result.command_id), "STATUS_LOST")
        self.assertFalse(nav.reached(nav_map, result))
        self.assertEqual(robot.posture, "POWERED_OFF")

    def test_a_stuck_robot_never_counts_as_arrived(self):
        robot = standing_robot()
        nav_map, nav = SpotMapEmulator(robot, steps_to_goal=2), SpotGraphNav()
        result = nav.go_to_waypoint(nav_map, accepted("WALK_TO", x=0.0, y=0.0), "bench", command_timeout_s=30)
        nav_map.get_stuck()
        nav_map.advance(10)
        self.assertEqual(nav_map.navigation_status(result.command_id), "STATUS_STUCK")
        self.assertFalse(nav.reached(nav_map, result))

    def test_a_sitting_robot_refuses_to_navigate_and_the_bridge_says_so(self):
        robot = SpotRobotEmulator()  # starts sitting
        result = SpotGraphNav().go_to_waypoint(SpotMapEmulator(robot), accepted("WALK_TO", x=0.0, y=0.0), "bench", command_timeout_s=30)
        self.assertFalse(result.sent)
        self.assertIn("must stand", result.reason)

    def test_an_engaged_stop_or_a_lost_lease_refuses_before_any_motion(self):
        for setup, text in ((lambda r: r.engage_estop(True), "not powered"), (lambda r: r.set_lease_held(False), "Lease")):
            robot = standing_robot()
            setup(robot)
            result = SpotGraphNav().go_to_waypoint(SpotMapEmulator(robot), accepted("WALK_TO", x=0.0, y=0.0), "bench", command_timeout_s=30)
            self.assertFalse(result.sent)
            self.assertIn(text, result.reason)

    def test_an_unreadable_map_and_an_unknown_name_send_nothing(self):
        robot = standing_robot()
        nav_map = SpotMapEmulator(robot)
        nav_map.map_unreadable = True
        self.assertFalse(SpotGraphNav().go_to_waypoint(nav_map, accepted("WALK_TO", x=0.0, y=0.0), "bench", command_timeout_s=30).sent)
        nav_map.map_unreadable = False
        self.assertFalse(SpotGraphNav().go_to_waypoint(nav_map, accepted("WALK_TO", x=0.0, y=0.0), "nowhere", command_timeout_s=30).sent)
        self.assertEqual(nav_map.navigations, [])

    def test_a_command_that_would_already_be_expired_is_refused(self):
        robot = standing_robot()
        result = SpotGraphNav().go_to_waypoint(
            SpotMapEmulator(robot), accepted("WALK_TO", x=0.0, y=0.0), "bench", command_timeout_s=30, clock=lambda: time.time() - 3600
        )
        self.assertFalse(result.sent)
        self.assertIn("expired", result.reason)

    def test_a_global_stop_announced_during_the_walk_cuts_the_robot(self):
        robot = standing_robot()
        parts = dict(estop=CuttingEstop(robot), lease=FakeLease(), power=FakePower(robot), state=FakeState(robot))
        session = SpotSession(parts["estop"], parts["lease"], parts["power"], parts["state"], SpotSessionConfig(), Clock())
        self.assertTrue(session.bring_up().ok)
        guard = GlobalStopGuard(GlobalStopSettings(enabled=True))
        bridge = DroidMqttBridge(DroidCoordinator(), lambda: CellState.READY, session, global_stop=guard)
        nav_map, nav = SpotMapEmulator(robot, steps_to_goal=6), SpotGraphNav()
        result = nav.go_to_waypoint(nav_map, accepted("WALK_TO", x=0.0, y=0.0), "bench", command_timeout_s=30)
        nav_map.advance(2)
        bridge.note_global_stop(b'{"state":"SAFE_STOP"}')
        nav_map.advance(4)
        self.assertFalse(session.ready)
        self.assertEqual(nav_map.navigation_status(result.command_id), "STATUS_LOST")
        self.assertFalse(nav.reached(nav_map, result))


class ArmScenarioTests(unittest.TestCase):
    def test_pick_then_place_changes_the_gripper_only_when_the_robot_confirms(self):
        robot = standing_robot()
        arm, control = SpotArmEmulator(robot), SpotArmControl()
        picked = control.pick(arm, accepted("PICK_OBJECT", object_id="cup-3"), detected_object_ids={"cup-3"})
        self.assertTrue(picked.sent)
        self.assertFalse(arm.holding())  # sent is not held
        arm.settle()
        self.assertTrue(arm.holding())
        placed = control.place(arm, accepted("PLACE_OBJECT", x=0.4, y=0.1), max_reach_m=1.0)
        self.assertTrue(placed.sent)
        self.assertFalse(arm.holding())

    def test_an_object_without_a_valid_grasp_is_reported_not_sent(self):
        robot = standing_robot()
        arm = SpotArmEmulator(robot, graspable={"cup-3"})
        result = SpotArmControl().pick(arm, accepted("PICK_OBJECT", object_id="box-1"), detected_object_ids={"box-1"})
        self.assertFalse(result.sent)
        self.assertIn("no valid grasp", result.reason)
        self.assertFalse(arm.holding())

    def test_a_second_pick_with_a_full_gripper_never_reaches_the_arm(self):
        robot = standing_robot()
        arm, control = SpotArmEmulator(robot, graspable={"a", "b"}), SpotArmControl()
        self.assertTrue(control.pick(arm, accepted("PICK_OBJECT", object_id="a"), detected_object_ids={"a", "b"}).sent)
        arm.settle()
        self.assertFalse(control.pick(arm, accepted("PICK_OBJECT", object_id="b"), detected_object_ids={"a", "b"}).sent)
        self.assertEqual(arm.calls, [("grasp", "a")])

    def test_the_emergency_stop_before_the_grasp_closes_leaves_the_gripper_empty(self):
        robot = standing_robot()
        arm = SpotArmEmulator(robot)
        self.assertTrue(SpotArmControl().pick(arm, accepted("PICK_OBJECT", object_id="cup-3"), detected_object_ids={"cup-3"}).sent)
        robot.engage_estop(True)
        arm.settle()
        self.assertFalse(arm.holding())

    def test_after_the_stop_the_arm_refuses_every_order(self):
        robot = standing_robot()
        arm, control = SpotArmEmulator(robot), SpotArmControl()
        control.pick(arm, accepted("PICK_OBJECT", object_id="cup-3"), detected_object_ids={"cup-3"})
        arm.settle()
        robot.engage_estop(True)
        arm.drop_on_power_loss()
        self.assertFalse(arm.holding())
        self.assertFalse(control.pick(arm, accepted("PICK_OBJECT", object_id="cup-3"), detected_object_ids={"cup-3"}).sent)

    def test_the_arm_does_not_work_while_the_robot_walks_or_sits(self):
        for posture in ("MOVING", "SITTING"):
            robot = SpotRobotEmulator()
            robot.posture = posture
            result = SpotArmControl().pick(SpotArmEmulator(robot), accepted("PICK_OBJECT", object_id="cup-3"), detected_object_ids={"cup-3"})
            self.assertFalse(result.sent, posture)

    def test_a_point_beyond_the_reach_is_refused_with_the_object_still_held(self):
        robot = standing_robot()
        arm, control = SpotArmEmulator(robot), SpotArmControl()
        control.pick(arm, accepted("PICK_OBJECT", object_id="cup-3"), detected_object_ids={"cup-3"})
        arm.settle()
        self.assertFalse(control.place(arm, accepted("PLACE_OBJECT", x=2.5, y=0.0), max_reach_m=1.0).sent)
        self.assertTrue(arm.holding())


if __name__ == "__main__":
    unittest.main()
