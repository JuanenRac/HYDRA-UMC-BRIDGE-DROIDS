# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - tests/test_robot_state_fixtures.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The state the gate may trust, read from fixtures shaped like `MessageToDict(RobotState)`: standing, walking, turning, e-stopped, motors off and no motion data.

The fixtures are written by hand from the documented shape of the message; a recording of a real RobotState replaces them when a robot is available."""

import json
import unittest
from pathlib import Path

from hydra_umc_sdk.bridge_contract import MachineState

from hydra_umc_bridge_droids import SpotSessionConfig

from test_spot_session import make_session

DATA = Path(__file__).resolve().parent / "data"


def observed(fixture, **config):
    session, _, _, clock = make_session(SpotSessionConfig(**config))
    session._last_state = json.loads((DATA / fixture).read_text(encoding="utf-8"))
    session._last_state_at = clock()
    return session.observed_machine_state()


class RobotStateFixtureTests(unittest.TestCase):
    def test_the_table_of_fixtures(self):
        table = {
            "robot_state_standing.json": MachineState.IDLE,
            "robot_state_walking.json": MachineState.RUNNING,
            "robot_state_turning.json": MachineState.RUNNING,
            "robot_state_estopped.json": MachineState.STOPPED,
            "robot_state_motors_off.json": MachineState.OFFLINE,
            "robot_state_no_motion_data.json": None,  # whether it moves is unknown: not read as free
        }
        for fixture, expected in table.items():
            with self.subTest(fixture):
                self.assertEqual(observed(fixture), expected)

    def test_a_state_with_no_motion_data_is_idle_only_when_the_setting_says_so(self):
        self.assertIsNone(observed("robot_state_no_motion_data.json", unknown_motion_is_idle=False))
        self.assertEqual(observed("robot_state_no_motion_data.json", unknown_motion_is_idle=True), MachineState.IDLE)
        self.assertEqual(observed("robot_state_walking.json", unknown_motion_is_idle=False), MachineState.RUNNING)
        self.assertEqual(observed("robot_state_standing.json", unknown_motion_is_idle=False), MachineState.IDLE)

    def test_the_speed_threshold_is_a_setting(self):
        self.assertEqual(observed("robot_state_walking.json", moving_speed_mps=1.0), MachineState.IDLE)

    def test_the_new_settings_are_checked(self):
        self.assertTrue(SpotSessionConfig(unknown_motion_is_idle="yes").problems())
        self.assertTrue(SpotSessionConfig(moving_speed_mps=0).problems())
        self.assertEqual(SpotSessionConfig().problems(), [])


if __name__ == "__main__":
    unittest.main()
