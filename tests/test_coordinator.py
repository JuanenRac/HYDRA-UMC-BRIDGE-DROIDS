# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - Coordinator tests
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================

import unittest

from hydra_umc_bridge_droids import BridgeJob, CellState, DroidCoordinator, JobPhase, MachineState


def job(phase=JobPhase.PROCESS, state=MachineState.IDLE, parameters=None):
    return BridgeJob("job-1", "idempotency-1", "droid-1", phase, state, parameters or {})


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.coordinator = DroidCoordinator()

    def test_walk_to_with_real_coordinates_is_accepted(self):
        result = self.coordinator.dispatch(job(parameters={"x": "1.5", "y": "2.0"}), CellState.READY)
        self.assertTrue(result.accepted)
        self.assertEqual(result.action, "WALK_TO")

    def test_walk_to_without_coordinates_is_rejected_before_any_transport(self):
        result = self.coordinator.dispatch(job(parameters={}), CellState.READY)
        self.assertFalse(result.accepted)
        self.assertIn("x", result.reason)
        self.assertIn("y", result.reason)

    def test_movement_rejects_non_numeric_or_non_finite_coordinates(self):
        for coordinates in (
            {"x": "east", "y": "2"},
            {"x": "nan", "y": "2"},
            {"x": "1", "y": "inf"},
        ):
            with self.subTest(coordinates=coordinates):
                result = self.coordinator.dispatch(job(parameters=coordinates), CellState.READY)
                self.assertFalse(result.accepted)
                self.assertIn("finite numeric", result.reason)

    def test_pick_object_requires_object_id(self):
        rejected = self.coordinator.dispatch(job(JobPhase.LOAD, parameters={}), CellState.READY)
        self.assertFalse(rejected.accepted)
        self.assertEqual(rejected.action, "PICK_OBJECT")
        accepted = self.coordinator.dispatch(job(JobPhase.LOAD, parameters={"object_id": "crate-7"}), CellState.READY)
        self.assertTrue(accepted.accepted)

    def test_pick_object_rejects_a_blank_object_id(self):
        result = self.coordinator.dispatch(job(JobPhase.LOAD, parameters={"object_id": "  "}), CellState.READY)
        self.assertFalse(result.accepted)
        self.assertIn("non-empty", result.reason)

    def test_busy_machine_is_not_reused(self):
        result = self.coordinator.dispatch(job(state=MachineState.RUNNING, parameters={"x": "0", "y": "0"}), CellState.READY)
        self.assertFalse(result.accepted)

    def test_hold_position_needs_no_parameters_and_stays_available_during_fault(self):
        result = self.coordinator.dispatch(job(JobPhase.ABORT, MachineState.FAULT, {}), CellState.FAULT)
        self.assertTrue(result.accepted)
        self.assertEqual(result.action, "HOLD_POSITION")

    def test_complete_returns_home_with_no_parameters_required(self):
        result = self.coordinator.dispatch(job(JobPhase.COMPLETE, parameters={}), CellState.READY)
        self.assertTrue(result.accepted)
        self.assertEqual(result.action, "RETURN_HOME")

    def test_unknown_sdk_phase_fails_closed_instead_of_guessing_an_action(self):
        unknown = BridgeJob("job-2", "idempotency-2", "droid-1", "SOME_FUTURE_PHASE", MachineState.IDLE, {})
        result = self.coordinator.dispatch(unknown, CellState.READY)
        self.assertFalse(result.accepted)
        self.assertEqual(result.action, "none")

    def test_action_plan_is_static_and_explicitly_not_a_runtime(self):
        plan = self.coordinator.action_plan().to_dict()
        self.assertEqual(plan["schema_version"], "1.0")
        self.assertEqual(plan["mode"], "plan-only")
        self.assertIn("WALK_TO", plan["actions"])
        self.assertIn("PICK_OBJECT", plan["actions"])


if __name__ == "__main__":
    unittest.main()
