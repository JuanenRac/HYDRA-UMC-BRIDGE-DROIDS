# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - Platform profile and simulated droid tests
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================

import unittest

from hydra_umc_bridge_droids import BridgeJob, CellState, DroidCoordinator, JobPhase, MachineState
from hydra_umc_bridge_droids.platform_profiles import (
    MOBILE_MANIPULATOR,
    MOBILE_ONLY,
    PROFILES,
    SimulatedDroid,
    check_against_profile,
)


def dispatch(phase, cell=CellState.READY):
    params = {"x": "1.0", "y": "2.0", "object_id": "box-1"}
    job = BridgeJob("job-1", "idem-1", "droid-1", phase, MachineState.IDLE, params)
    return DroidCoordinator().dispatch(job, cell)


class PlatformProfileTests(unittest.TestCase):
    def test_every_coordinator_action_is_known_to_the_manipulator_profile(self):
        self.assertEqual(MOBILE_MANIPULATOR.actions, set(DroidCoordinator._REQUIRED_PARAMS))

    def test_mobile_only_refuses_pick_and_place(self):
        for phase in (JobPhase.LOAD, JobPhase.UNLOAD):
            result = check_against_profile(dispatch(phase), MOBILE_ONLY)
            self.assertFalse(result.accepted)
            self.assertIn("mobile-only", result.reason)

    def test_manipulator_accepts_pick_and_place(self):
        for phase in (JobPhase.LOAD, JobPhase.UNLOAD):
            self.assertTrue(check_against_profile(dispatch(phase), MOBILE_MANIPULATOR).accepted)

    def test_stop_is_never_blocked_by_a_profile(self):
        stop = dispatch(JobPhase.ABORT, cell=CellState.FAULT)
        self.assertTrue(check_against_profile(stop, MOBILE_ONLY).accepted)

    def test_an_already_refused_dispatch_is_returned_untouched(self):
        refused = dispatch(JobPhase.PREPARE, cell=CellState.SAFE_STOP)
        self.assertIs(check_against_profile(refused, MOBILE_MANIPULATOR), refused)

    def test_simulated_droid_records_only_what_the_profile_accepts(self):
        droid = SimulatedDroid(MOBILE_ONLY)
        for phase in (JobPhase.PREPARE, JobPhase.LOAD, JobPhase.PROCESS, JobPhase.COMPLETE):
            droid.apply(dispatch(phase))
        self.assertEqual(droid.executed, ("WALK_TO", "WALK_TO", "RETURN_HOME"))

    def test_profiles_are_registered_by_name(self):
        self.assertEqual(set(PROFILES), {"mobile-only", "mobile-manipulator"})

    def test_module_imports_no_transport(self):
        import hydra_umc_bridge_droids.platform_profiles as module

        code = open(module.__file__, encoding="utf-8").read().split('"""', 2)[2]
        self.assertNotIn("spot_transport", code)


if __name__ == "__main__":
    unittest.main()
