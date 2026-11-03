# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - Spot session, GraphNav and arm tests (emulated Spot)
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The session, the named-waypoint navigation and the arm against fakes and the Spot emulator."""

import json
import tempfile
import unittest
from pathlib import Path

from hydra_umc_sdk.bridge_contract import MachineState
from hydra_umc_bridge_droids import (
    DroidDispatch,
    SpotArmControl,
    SpotGraphNav,
    SpotSession,
    SpotSessionConfig,
    load_session_config,
)

from spot_emulator import SpotRobotEmulator


class FakeEstop:
    def __init__(self):
        self.calls, self.check_in_ok, self.fail_register = [], True, False

    def register(self):
        if self.fail_register:
            raise OSError("estop service unreachable")
        self.calls.append("register")

    def check_in(self):
        return self.check_in_ok

    def cut(self):
        self.calls.append("cut")

    def allow(self):
        self.calls.append("allow")


class FakeLease:
    def __init__(self):
        self.alive, self.calls, self.fail = True, [], False

    def acquire(self):
        if self.fail:
            raise OSError("lease held by another operator")
        self.calls.append("acquire")

    def is_alive(self):
        return self.alive

    def release(self):
        self.calls.append("release")


class FakePower:
    def __init__(self, robot, powers_on=True):
        self.robot, self.powers_on, self.calls = robot, powers_on, []

    def power_on(self, timeout_s):
        self.calls.append(("on", timeout_s))
        if self.powers_on:
            self.robot.powered_on = True
            self.robot.posture = "STANDING"
        return self.powers_on

    def power_off(self, timeout_s):
        self.calls.append(("off", timeout_s))
        self.robot.power_off()
        return True


class FakeState:
    def __init__(self, robot):
        self.robot, self.fail = robot, False

    def get_robot_state(self):
        if self.fail:
            raise OSError("no answer")
        return self.robot.emit_robot_state()


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_session(config=None, robot=None):
    robot = robot or SpotRobotEmulator()
    clock = Clock()
    parts = dict(estop=FakeEstop(), lease=FakeLease(), power=FakePower(robot), state=FakeState(robot))
    session = SpotSession(parts["estop"], parts["lease"], parts["power"], parts["state"], config or SpotSessionConfig(), clock)
    return session, robot, parts, clock


class SessionBringUpTests(unittest.TestCase):
    def test_bring_up_does_not_power_the_motors_by_default(self):
        session, _, parts, _ = make_session()
        result = session.bring_up()
        self.assertTrue(result.ok)
        self.assertEqual(parts["estop"].calls, ["register", "allow"])
        self.assertEqual(parts["lease"].calls, ["acquire"])
        self.assertEqual(parts["power"].calls, [])

    def test_power_on_only_when_the_configuration_asks_for_it(self):
        session, _, parts, _ = make_session(SpotSessionConfig(power_on_after_bring_up=True, power_timeout_s=12))
        self.assertTrue(session.bring_up().ok)
        self.assertEqual(parts["power"].calls, [("on", 12)])

    def test_motors_that_do_not_power_on_fail_closed(self):
        session, _, parts, _ = make_session(SpotSessionConfig(power_on_after_bring_up=True))
        parts["power"].powers_on = False
        result = session.bring_up()
        self.assertFalse(result.ok)
        self.assertFalse(session.ready)
        self.assertIn("cut", parts["estop"].calls)

    def test_a_lease_held_by_someone_else_stops_the_bring_up(self):
        session, _, parts, _ = make_session()
        parts["lease"].fail = True
        result = session.bring_up()
        self.assertFalse(result.ok)
        self.assertIn("lease", result.reason)
        self.assertEqual(session.observed_machine_state(), MachineState.SAFE_STOP)

    def test_an_unreachable_estop_stops_the_bring_up_before_the_lease(self):
        session, _, parts, _ = make_session()
        parts["estop"].fail_register = True
        self.assertFalse(session.bring_up().ok)
        self.assertEqual(parts["lease"].calls, [])

    def test_a_low_battery_is_refused(self):
        robot = SpotRobotEmulator()
        robot.set_battery(12)
        session, _, _, _ = make_session(robot=robot)
        result = session.bring_up()
        self.assertFalse(result.ok)
        self.assertIn("battery", result.reason)

    def test_a_state_that_cannot_be_read_is_refused(self):
        session, _, parts, _ = make_session()
        parts["state"].fail = True
        self.assertFalse(session.bring_up().ok)

    def test_a_bad_configuration_is_refused(self):
        session, _, _, _ = make_session(SpotSessionConfig(estop_timeout_s=float("nan")))
        result = session.bring_up()
        self.assertFalse(result.ok)
        self.assertIn("estop_timeout_s", result.reason)


class SessionKeepAliveTests(unittest.TestCase):
    def setUp(self):
        self.session, self.robot, self.parts, self.clock = make_session()
        self.assertTrue(self.session.bring_up().ok)

    def test_a_healthy_tick_stays_alive(self):
        self.assertTrue(self.session.tick().ok)

    def test_a_refused_check_in_cuts_the_robot(self):
        self.parts["estop"].check_in_ok = False
        self.assertFalse(self.session.tick().ok)
        self.assertIn("cut", self.parts["estop"].calls)
        self.assertEqual(self.session.observed_machine_state(), MachineState.SAFE_STOP)

    def test_a_lost_lease_cuts_the_session(self):
        self.parts["lease"].alive = False
        result = self.session.tick()
        self.assertFalse(result.ok)
        self.assertIn("lease", result.reason)
        self.assertFalse(self.session.tick().ok)

    def test_shutdown_powers_off_and_releases_the_lease(self):
        result = self.session.shutdown()
        self.assertIn("lease released", result.steps)
        self.assertEqual(self.parts["power"].calls, [("off", 30.0)])
        self.assertFalse(self.session.ready)


class ObservedStateTests(unittest.TestCase):
    def observed(self, robot):
        session, _, _, _ = make_session(robot=robot)
        self.assertTrue(session.bring_up().ok)
        return session.observed_machine_state()

    def test_standing_with_motors_on_is_idle(self):
        robot = SpotRobotEmulator()
        robot.posture = "STANDING"
        self.assertEqual(self.observed(robot), MachineState.IDLE)

    def test_walking_is_running(self):
        robot = SpotRobotEmulator()
        robot.posture = "MOVING"
        self.assertEqual(self.observed(robot), MachineState.RUNNING)

    def test_motors_off_is_offline(self):
        robot = SpotRobotEmulator()
        robot.power_off()
        self.assertEqual(self.observed(robot), MachineState.OFFLINE)

    def test_a_behavior_fault_is_fault(self):
        robot = SpotRobotEmulator()
        robot.raise_behavior_fault()
        self.assertEqual(self.observed(robot), MachineState.FAULT)

    def test_an_engaged_estop_is_stopped(self):
        robot = SpotRobotEmulator()
        robot.engage_estop()
        self.assertEqual(self.observed(robot), MachineState.STOPPED)

    def test_a_battery_under_the_floor_while_running_holds(self):
        robot = SpotRobotEmulator()
        session, _, _, _ = make_session(SpotSessionConfig(min_battery_pct=10), robot=robot)
        self.assertTrue(session.bring_up().ok)
        robot.set_battery(8)
        session.read_state()
        self.assertEqual(session.observed_machine_state(), MachineState.HOLDING)

    def test_an_old_reading_is_not_trusted(self):
        session, _, _, clock = make_session()
        self.assertTrue(session.bring_up().ok)
        clock.now += 60
        self.assertIsNone(session.observed_machine_state())

    def test_a_real_state_dictionary_wraps_the_battery_in_a_value(self):
        session, _, parts, _ = make_session()
        state = parts["state"].robot.emit_robot_state()
        state["battery_states"] = [{"charge_percentage": {"value": 5.0}}]
        parts["state"].get_robot_state = lambda: state
        self.assertFalse(session.bring_up().ok)


class ConfigFileTests(unittest.TestCase):
    def write(self, content):
        directory = tempfile.mkdtemp()
        path = Path(directory) / "session.json"
        path.write_text(json.dumps(content), encoding="utf-8")
        return path

    def test_no_file_gives_the_conservative_defaults(self):
        config = load_session_config(None)
        self.assertFalse(config.power_on_after_bring_up)
        self.assertEqual(config.problems(), [])

    def test_values_are_read_from_the_file(self):
        config = load_session_config(self.write({"min_battery_pct": 35, "home_waypoint": "dock"}))
        self.assertEqual((config.min_battery_pct, config.home_waypoint), (35, "dock"))

    def test_an_unknown_key_is_an_error(self):
        with self.assertRaises(ValueError):
            load_session_config(self.write({"min_batery_pct": 35}))

    def test_a_bad_value_is_an_error(self):
        with self.assertRaises(ValueError):
            load_session_config(self.write({"min_battery_pct": 400}))

    def test_the_shipped_example_is_valid(self):
        path = Path(__file__).resolve().parent.parent / "config" / "spot_session.json"
        self.assertTrue(path.is_file())
        self.assertEqual(load_session_config(path).problems(), [])


class FakeMap:
    def __init__(self):
        self.waypoints = {"dock": "wp-1", "bench": "wp-2"}
        self.navigated, self.fail_navigate, self.status = [], False, "STATUS_REACHED_GOAL"

    def waypoint_id_for(self, name):
        return self.waypoints.get(name)

    def navigate_to(self, waypoint_id, end_time_secs):
        if self.fail_navigate:
            raise OSError("graph not uploaded")
        self.navigated.append((waypoint_id, end_time_secs))
        return 7

    def navigation_status(self, command_id):
        return self.status


def accepted(action, **parameters):
    return DroidDispatch(True, action, "ok", parameters=parameters)


class GraphNavTests(unittest.TestCase):
    def test_walk_to_a_named_waypoint(self):
        sink, nav = FakeMap(), SpotGraphNav()
        result = nav.go_to_waypoint(sink, accepted("WALK_TO", x=1.0, y=2.0), "bench", command_timeout_s=30, clock=lambda: 100.0)
        self.assertTrue(result.sent)
        self.assertEqual(sink.navigated, [("wp-2", 130.0)])
        self.assertTrue(nav.reached(sink, result))

    def test_return_home_uses_the_configured_waypoint(self):
        sink, nav = FakeMap(), SpotGraphNav(SpotSessionConfig(home_waypoint="dock"))
        result = nav.return_home(sink, accepted("RETURN_HOME"), command_timeout_s=60, clock=lambda: 0.0)
        self.assertEqual((result.sent, result.waypoint_id), (True, "wp-1"))

    def test_an_unknown_waypoint_sends_nothing(self):
        sink = FakeMap()
        result = SpotGraphNav().go_to_waypoint(sink, accepted("WALK_TO", x=0.0, y=0.0), "nowhere", command_timeout_s=30)
        self.assertFalse(result.sent)
        self.assertEqual(sink.navigated, [])

    def test_a_refused_dispatch_never_reaches_the_map(self):
        sink = FakeMap()
        refused = DroidDispatch(False, "WALK_TO", "cell not ready")
        self.assertFalse(SpotGraphNav().go_to_waypoint(sink, refused, "bench", command_timeout_s=30).sent)
        self.assertEqual(sink.navigated, [])

    def test_a_dispatch_of_another_action_is_refused(self):
        self.assertFalse(SpotGraphNav().return_home(FakeMap(), accepted("WALK_TO", x=0.0, y=0.0), command_timeout_s=30).sent)

    def test_a_bad_timeout_is_refused(self):
        for bad in (0, -1, float("inf"), True):
            self.assertFalse(SpotGraphNav().go_to_waypoint(FakeMap(), accepted("WALK_TO", x=0.0, y=0.0), "bench", command_timeout_s=bad).sent)

    def test_a_navigation_failure_is_reported_not_raised(self):
        sink = FakeMap()
        sink.fail_navigate = True
        result = SpotGraphNav().go_to_waypoint(sink, accepted("WALK_TO", x=0.0, y=0.0), "bench", command_timeout_s=30)
        self.assertFalse(result.sent)
        self.assertIn("graph not uploaded", result.reason)


class FakeArm:
    def __init__(self, holding=False):
        self._holding, self.calls = holding, []

    def holding(self):
        return self._holding

    def grasp_object(self, object_id):
        self.calls.append(("grasp", object_id))
        return 11

    def place_at(self, x, y):
        self.calls.append(("place", x, y))
        return 12


class ArmTests(unittest.TestCase):
    def test_pick_a_detected_object(self):
        arm = FakeArm()
        result = SpotArmControl().pick(arm, accepted("PICK_OBJECT", object_id="cup-3"), detected_object_ids={"cup-3"})
        self.assertTrue(result.sent)
        self.assertEqual(arm.calls, [("grasp", "cup-3")])

    def test_an_object_the_vision_node_does_not_report_is_not_grasped(self):
        arm = FakeArm()
        result = SpotArmControl().pick(arm, accepted("PICK_OBJECT", object_id="cup-3"), detected_object_ids={"box-1"})
        self.assertFalse(result.sent)
        self.assertEqual(arm.calls, [])

    def test_a_full_gripper_does_not_pick(self):
        self.assertFalse(SpotArmControl().pick(FakeArm(holding=True), accepted("PICK_OBJECT", object_id="a"), detected_object_ids={"a"}).sent)

    def test_place_inside_the_reach(self):
        arm = FakeArm(holding=True)
        self.assertTrue(SpotArmControl().place(arm, accepted("PLACE_OBJECT", x=0.5, y=0.2), max_reach_m=1.0).sent)
        self.assertEqual(arm.calls, [("place", 0.5, 0.2)])

    def test_place_beyond_the_reach_is_refused(self):
        arm = FakeArm(holding=True)
        self.assertFalse(SpotArmControl().place(arm, accepted("PLACE_OBJECT", x=3.0, y=0.0), max_reach_m=1.0).sent)
        self.assertEqual(arm.calls, [])

    def test_place_with_an_empty_gripper_is_refused(self):
        self.assertFalse(SpotArmControl().place(FakeArm(), accepted("PLACE_OBJECT", x=0.1, y=0.1), max_reach_m=1.0).sent)

    def test_refused_or_wrong_dispatches_do_nothing(self):
        arm = FakeArm(holding=True)
        control = SpotArmControl()
        self.assertFalse(control.pick(arm, DroidDispatch(False, "PICK_OBJECT", "no"), detected_object_ids={"a"}).sent)
        self.assertFalse(control.place(arm, accepted("WALK_TO", x=0.0, y=0.0), max_reach_m=1.0).sent)
        self.assertEqual(arm.calls, [])


if __name__ == "__main__":
    unittest.main()
