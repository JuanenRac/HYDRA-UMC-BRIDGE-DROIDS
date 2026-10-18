# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - Stop and sit ordering, command status and bring-up edge cases
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
import math
import sys
import types
import unittest
from unittest import mock

from hydra_umc_sdk.bridge_contract import CellState, MachineState

from hydra_umc_bridge_droids import DroidCoordinator, DroidDispatch, SpotDroidControl, open_bosdyn_robot_command


class Builder:
    def __init__(self):
        self.calls = []

    def synchro_stand_command(self):
        self.calls.append("stand")
        return "STAND"

    def synchro_sit_command(self):
        self.calls.append("sit")
        return "SIT"

    def stop_command(self):
        self.calls.append("stop")
        return "STOP"

    def synchro_trajectory_command_in_body_frame(self, x, y, heading, snapshot):
        self.calls.append(("walk", x, y, heading))
        return "WALK"


class Sink:
    def __init__(self, response=None, fail_on=None):
        self.sent, self.response, self.fail_on = [], response, fail_on

    def robot_command(self, command, end_time_secs=None):
        if command == self.fail_on:
            raise OSError("radio down")
        self.sent.append((command, end_time_secs))
        return self.response


def walk(x=1.0, y=2.0, accepted=True, action=DroidCoordinator.WALK_TO):
    return DroidDispatch(accepted, action, "ok", parameters={"x": x, "y": y})


class StopAndSitTests(unittest.TestCase):
    def test_a_stop_goes_out_whatever_the_dispatch_gate_or_machine_say(self):
        builder, sink = Builder(), Sink()
        for dispatch in (None, DroidDispatch(False, DroidCoordinator.HOLD_POSITION, "cell is FAULT")):
            self.assertTrue(SpotDroidControl().hold_position(builder, sink, dispatch).sent)
        self.assertEqual(sink.sent, [("STOP", None), ("STOP", None)])

    def test_a_stop_will_not_be_used_to_carry_another_action(self):
        builder, sink = Builder(), Sink()
        result = SpotDroidControl().hold_position(builder, sink, walk())
        self.assertFalse(result.sent)
        self.assertEqual(sink.sent, [])

    def test_sit_stops_first_and_does_not_sit_when_the_stop_failed(self):
        builder, sink = Builder(), Sink(fail_on="STOP")
        result = SpotDroidControl().sit(builder, sink)
        self.assertFalse(result.sent)
        self.assertIn("could not be stopped first", result.reason)
        self.assertNotIn("sit", builder.calls)

    def test_sit_without_the_stop_sends_only_the_sit(self):
        builder, sink = Builder(), Sink()
        self.assertTrue(SpotDroidControl().sit(builder, sink, stop_first=False).sent)
        self.assertEqual([c for c, _ in sink.sent], ["SIT"])

    def test_stand_needs_a_ready_cell_and_an_idle_machine_and_otherwise_sends_nothing(self):
        for cell, machine in ((CellState.FAULT, MachineState.IDLE), (CellState.READY, MachineState.RUNNING), (CellState.READY, MachineState.FAULT), (CellState.READY, MachineState.SAFE_STOP)):
            builder, sink = Builder(), Sink()
            self.assertFalse(SpotDroidControl().stand(builder, sink, cell, machine).sent, (cell, machine))
            self.assertEqual((builder.calls, sink.sent), ([], []))


class CommandStatusTests(unittest.TestCase):
    def test_a_response_with_a_status_other_than_ok_is_not_a_success(self):
        for status in (0, 2, 3, -1, "STATUS_OK"):
            response = types.SimpleNamespace(status=status)
            result = SpotDroidControl().hold_position(Builder(), Sink(response=response))
            self.assertFalse(result.sent, status)

    def test_a_response_with_status_ok_or_no_status_at_all_is_a_success(self):
        self.assertTrue(SpotDroidControl().hold_position(Builder(), Sink(response=types.SimpleNamespace(status=1))).sent)
        self.assertTrue(SpotDroidControl().hold_position(Builder(), Sink(response=123)).sent)
        self.assertTrue(SpotDroidControl().hold_position(Builder(), Sink(response=None)).sent)


class WalkTests(unittest.TestCase):
    def go(self, dispatch, **kw):
        builder, sink = Builder(), Sink()
        kw.setdefault("frame_tree_snapshot", object())
        kw.setdefault("command_timeout_s", 5.0)
        result = SpotDroidControl().walk_to(builder, sink, dispatch, clock=lambda: 100.0, **kw)
        return result, builder, sink

    def test_the_command_expires_a_fixed_time_after_now(self):
        result, _, sink = self.go(walk())
        self.assertTrue(result.sent)
        self.assertEqual(sink.sent[0][1], 105.0)

    def test_the_goal_sent_is_the_validated_one(self):
        _, builder, _ = self.go(walk(3.0, 4.0), goal_heading=0.5)
        self.assertEqual(builder.calls, [("walk", 3.0, 4.0, 0.5)])

    def test_the_distance_limit_is_inclusive(self):
        self.assertTrue(self.go(walk(3.0, 4.0), max_distance_m=5.0)[0].sent)
        self.assertFalse(self.go(walk(3.0, 4.01), max_distance_m=5.0)[0].sent)

    def test_bad_numbers_never_reach_the_robot(self):
        cases = [
            dict(dispatch=walk(math.nan, 1)), dict(dispatch=walk(1, math.inf)), dict(dispatch=walk(True, 1)),
            dict(dispatch=walk("1", 1)), dict(dispatch=walk(), command_timeout_s=0), dict(dispatch=walk(), command_timeout_s=-1),
            dict(dispatch=walk(), command_timeout_s=math.nan), dict(dispatch=walk(), goal_heading=math.nan),
            dict(dispatch=walk(), max_distance_m=0), dict(dispatch=walk(), max_distance_m=math.inf),
            dict(dispatch=DroidDispatch(True, DroidCoordinator.WALK_TO, "ok", parameters={})),
        ]
        for case in cases:
            result, builder, sink = self.go(**case)
            self.assertFalse(result.sent, case)
            self.assertEqual((builder.calls, sink.sent), ([], []), case)


class BringUpTests(unittest.TestCase):
    def fake_bosdyn(self):
        builder_class, client_class = object(), types.SimpleNamespace(default_service_name="robot-command")
        command_client = object()
        robot = mock.MagicMock()
        robot.ensure_client.return_value = command_client
        sdk = mock.MagicMock()
        sdk.create_robot.return_value = robot
        bosdyn = types.ModuleType("bosdyn")
        client = types.ModuleType("bosdyn.client")
        client.create_standard_sdk = mock.MagicMock(return_value=sdk)
        util = types.ModuleType("bosdyn.client.util")
        robot_command = types.ModuleType("bosdyn.client.robot_command")
        robot_command.RobotCommandBuilder = builder_class
        robot_command.RobotCommandClient = client_class
        bosdyn.client = client
        client.util = util
        client.robot_command = robot_command
        modules = {"bosdyn": bosdyn, "bosdyn.client": client, "bosdyn.client.util": util, "bosdyn.client.robot_command": robot_command}
        return modules, robot, builder_class, command_client

    def test_the_bring_up_authenticates_waits_for_time_sync_and_returns_builder_and_client(self):
        modules, robot, builder_class, command_client = self.fake_bosdyn()
        with mock.patch.dict(sys.modules, modules):
            builder, sink = open_bosdyn_robot_command("192.0.2.10", "user", "pw")
        self.assertIs(builder, builder_class)
        self.assertIs(sink, command_client)
        robot.authenticate.assert_called_once_with("user", "pw")
        robot.time_sync.wait_for_sync.assert_called_once()
        robot.ensure_client.assert_called_once_with("robot-command")

    def test_an_authentication_failure_is_not_hidden(self):
        modules, robot, _, _ = self.fake_bosdyn()
        robot.authenticate.side_effect = RuntimeError("bad credentials")
        with mock.patch.dict(sys.modules, modules):
            with self.assertRaises(RuntimeError) as context:
                open_bosdyn_robot_command("192.0.2.10", "user", "wrong")
        self.assertIn("bad credentials", str(context.exception))
        robot.ensure_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
