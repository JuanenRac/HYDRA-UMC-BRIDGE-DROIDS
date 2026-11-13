# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - Going home as a de-escalation and the signed human confirmation
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""RETURN_HOME is forwarded whatever the machine reports; walking, picking and placing need a one-use confirmation signed by the server. Simulator evidence only."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from hydra_umc_sdk.bridge_contract import BridgeJob, CellState, JobPhase, MachineState, job_to_dict
from hydra_umc_sdk.global_stop import GlobalStopGuard, GlobalStopSettings

from hydra_umc_bridge_droids import DroidCoordinator, SpotSessionConfig
from hydra_umc_bridge_droids.droid_policy import CONFIRMATION_FIELD, DroidPolicy
from hydra_umc_bridge_droids.human_confirmation import ConfirmationError, ConfirmationVerifier, load_key, make_token
from hydra_umc_bridge_droids.mqtt_transport import TOPIC_PREFIX, DroidMqttBridge
from hydra_umc_bridge_droids.service import ConfigError, build_bridge, load_service_config

KEY = b"k" * 40
NOW = [2_000_000.0]


def clock() -> float:
    return NOW[0]


def token(action: str, job_id: str = "job-1", jti: str = "t1", ttl: float = 60.0, key: bytes = KEY, role: str = "operator") -> str:
    return make_token(key, operator="ana", role=role, action=action, job_id=job_id, token_id=jti, issued_at=NOW[0], ttl_s=ttl)


def job(phase: JobPhase, key: str = "k1", params: dict | None = None) -> BridgeJob:
    return BridgeJob("job-1", key, "droid-1", phase, MachineState.IDLE, params if params is not None else {"x": "1", "y": "2"})


class ReturnHomeTests(unittest.TestCase):
    def test_going_home_is_forwarded_while_the_droid_still_reports_running(self) -> None:
        # after PLACE_OBJECT the robot reports RUNNING: home used to be blocked until it said IDLE
        result = DroidCoordinator().dispatch(job(JobPhase.COMPLETE, params={}), CellState.READY, MachineState.RUNNING)
        self.assertTrue(result.accepted)
        self.assertEqual(result.action, "RETURN_HOME")
        self.assertIn("always forwarded", result.reason)

    def test_going_home_is_forwarded_whatever_the_cell_and_the_machine_say(self) -> None:
        coordinator = DroidCoordinator()
        for cell in CellState:
            for machine in (None, *MachineState):
                with self.subTest(cell=cell, machine=machine):
                    self.assertTrue(coordinator.dispatch(job(JobPhase.COMPLETE, params={}), cell, machine).accepted)

    def test_the_other_actions_keep_the_full_gate(self) -> None:
        coordinator = DroidCoordinator()
        self.assertFalse(coordinator.dispatch(job(JobPhase.PROCESS), CellState.READY, MachineState.RUNNING).accepted)
        self.assertFalse(coordinator.dispatch(job(JobPhase.UNLOAD), CellState.FAULT, MachineState.IDLE).accepted)

    def test_a_repeat_of_the_going_home_job_is_forwarded_again(self) -> None:
        coordinator = DroidCoordinator()
        payload = job_to_dict(job(JobPhase.COMPLETE, "home-1", {}))
        self.assertTrue(coordinator.handle_message(payload, CellState.READY, MachineState.RUNNING).accepted)
        self.assertTrue(coordinator.handle_message(payload, CellState.READY, MachineState.RUNNING).accepted)
        walk = job_to_dict(job(JobPhase.PROCESS, "walk-1"))
        self.assertTrue(coordinator.handle_message(walk, CellState.READY, MachineState.IDLE).accepted)
        self.assertFalse(coordinator.handle_message(walk, CellState.READY, MachineState.IDLE).accepted)

    def test_the_switch_puts_going_home_back_through_the_gate(self) -> None:
        strict = DroidCoordinator(return_home_always=False)
        result = strict.dispatch(job(JobPhase.COMPLETE, params={}), CellState.READY, MachineState.RUNNING)
        self.assertFalse(result.accepted)
        self.assertTrue(strict.dispatch(job(JobPhase.ABORT, params={}), CellState.FAULT, MachineState.FAULT).accepted)

    def test_request_for_reads_the_phase_safely(self) -> None:
        coordinator = DroidCoordinator()
        self.assertEqual(coordinator.request_for({"phase": "complete"}), "RETURN_HOME")
        self.assertIsNone(coordinator.request_for({"phase": 3}))
        self.assertIsNone(coordinator.request_for({"phase": "SOMETHING"}))

    def test_going_home_is_still_refused_during_the_global_stop(self) -> None:
        guard = GlobalStopGuard(GlobalStopSettings(enabled=True))
        guard.observe(json.dumps({"state": "SAFE_STOP"}).encode())
        session = SimpleNamespace(observed_machine_state=lambda: MachineState.RUNNING)
        bridge = DroidMqttBridge(DroidCoordinator(), lambda: CellState.READY, session, global_stop=guard)  # type: ignore[arg-type]
        body = json.dumps(job_to_dict(job(JobPhase.COMPLETE, "home-2", {}))).encode()
        out = bridge.handle_message(TOPIC_PREFIX + "cmd/job", body)
        self.assertFalse(json.loads(out[0].payload)["allowed"])


class TokenTests(unittest.TestCase):
    def setUp(self) -> None:
        NOW[0] = 2_000_000.0
        self.verifier = ConfirmationVerifier(KEY, clock=clock)

    def test_once_and_only_for_its_action_and_job(self) -> None:
        confirmation = self.verifier.verify(token("WALK_TO"), action="WALK_TO", job_id="job-1")
        self.assertTrue(self.verifier.consume(confirmation))
        with self.assertRaisesRegex(ConfirmationError, "already used"):
            self.verifier.verify(token("WALK_TO"), action="WALK_TO", job_id="job-1")
        with self.assertRaisesRegex(ConfirmationError, "not for PICK_OBJECT"):
            self.verifier.verify(token("WALK_TO", jti="b"), action="PICK_OBJECT", job_id="job-1")
        with self.assertRaisesRegex(ConfirmationError, "another job"):
            self.verifier.verify(token("WALK_TO", jti="c", job_id="x"), action="WALK_TO", job_id="job-1")

    def test_forged_expired_long_and_missing_are_refused(self) -> None:
        cases = {
            "forged": (token("WALK_TO", key=b"z" * 40), "signature"),
            "expired": (token("WALK_TO", ttl=-1), "expired"),
            "long": (token("WALK_TO", ttl=7200), "longer than"),
            "role": (token("WALK_TO", role="guest"), "role"),
            "missing": (None, "none came"),
            "garbage": ("a.b", "not a JWT"),
        }
        for name, (tok, why) in cases.items():
            with self.subTest(name), self.assertRaisesRegex(ConfirmationError, why):
                self.verifier.verify(tok, action="WALK_TO", job_id="job-1")

    def test_the_key_file_is_checked(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "key")
            path.write_text("short", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "at least"):
                load_key(str(path))
            with self.assertRaisesRegex(ValueError, "cannot be read"):
                load_key(str(Path(folder, "none")))


class BridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        NOW[0] = 2_000_000.0

    def make(self, policy: DroidPolicy | None, machine=MachineState.IDLE) -> DroidMqttBridge:
        session = SimpleNamespace(observed_machine_state=lambda: machine)
        return DroidMqttBridge(DroidCoordinator(), lambda: CellState.READY, session, global_stop=GlobalStopGuard(GlobalStopSettings(enabled=False)), policy=policy)  # type: ignore[arg-type]

    @staticmethod
    def send(bridge: DroidMqttBridge, phase: JobPhase, key: str, tok: str | None = None, params: dict | None = None) -> dict:
        raw = job_to_dict(job(phase, key, params))
        if tok is not None:
            raw[CONFIRMATION_FIELD] = tok
        return json.loads(bridge.handle_message(TOPIC_PREFIX + "cmd/job", json.dumps(raw).encode())[0].payload)

    def required(self) -> DroidPolicy:
        return DroidPolicy(True, ConfirmationVerifier(KEY, clock=clock))

    def test_a_job_that_moves_the_droid_needs_the_confirmation_and_the_key_stays_free(self) -> None:
        bridge = self.make(self.required())
        refused = self.send(bridge, JobPhase.PROCESS, "k1")
        self.assertFalse(refused["allowed"])
        self.assertEqual(refused["mode"], "refused")
        self.assertIn("none came", refused["reason"])
        accepted = self.send(bridge, JobPhase.PROCESS, "k1", token("WALK_TO"))
        self.assertTrue(accepted["allowed"], accepted)
        self.assertEqual(accepted["action"], "WALK_TO")

    def test_the_token_works_once(self) -> None:
        bridge = self.make(self.required())
        same = token("PICK_OBJECT")
        self.assertTrue(self.send(bridge, JobPhase.LOAD, "k1", same, {"object_id": "box"})["allowed"])
        again = self.send(bridge, JobPhase.LOAD, "k2", same, {"object_id": "box"})
        self.assertFalse(again["allowed"])
        self.assertIn("already used", again["reason"])

    def test_a_job_refused_by_the_gate_does_not_burn_the_token(self) -> None:
        shared = self.required()
        same = token("WALK_TO")
        busy = self.make(shared, MachineState.RUNNING)
        self.assertFalse(self.send(busy, JobPhase.PROCESS, "k1", same)["allowed"])
        idle = self.make(shared)
        self.assertTrue(self.send(idle, JobPhase.PROCESS, "k2", same)["allowed"])

    def test_going_home_and_aborting_need_no_confirmation(self) -> None:
        bridge = self.make(self.required(), MachineState.RUNNING)
        self.assertTrue(self.send(bridge, JobPhase.COMPLETE, "h1", params={})["allowed"])
        self.assertTrue(self.send(bridge, JobPhase.ABORT, "a1", params={})["allowed"])

    def test_without_a_key_the_job_is_refused(self) -> None:
        bridge = self.make(DroidPolicy(True, None))
        answer = self.send(bridge, JobPhase.PROCESS, "k1", token("WALK_TO"))
        self.assertFalse(answer["allowed"])
        self.assertIn("no confirmation key", answer["reason"])

    def test_the_switch_turns_the_check_off_and_no_policy_is_the_old_entry(self) -> None:
        self.assertTrue(self.send(self.make(DroidPolicy(False, None)), JobPhase.PROCESS, "k1")["allowed"])
        self.assertTrue(self.send(self.make(None), JobPhase.PROCESS, "k1")["allowed"])


class ServiceTests(unittest.TestCase):
    def test_the_shipped_configuration_is_the_conservative_one(self) -> None:
        config = load_service_config(Path(__file__).resolve().parent.parent / "config" / "bridge.json")
        self.assertTrue(config.policy.confirmation_required)
        self.assertTrue(config.policy.return_home_always)
        self.assertEqual(config.policy.confirmation_key_file, "")

    def test_bad_policy_values_are_errors(self) -> None:
        for body in ({"policy": {"confirmation_required": "yes"}}, {"policy": {"surprise": 1}}, {"policy": {"confirmation_max_ttl_s": 0}}, {"policy": {"confirmation_max_clock_skew_s": 600}}):
            with self.subTest(body), tempfile.TemporaryDirectory() as folder:
                path = Path(folder, "c.json")
                path.write_text(json.dumps(body), encoding="utf-8")
                with self.assertRaises(ConfigError):
                    load_service_config(path)

    def test_the_service_builds_the_policy_from_the_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            key = Path(folder, "key")
            key.write_text("q" * 40, encoding="utf-8")
            path = Path(folder, "c.json")
            path.write_text(json.dumps({"policy": {"confirmation_key_file": str(key), "return_home_always": False}}), encoding="utf-8")
            bridge = build_bridge(load_service_config(path), SpotSessionConfig())
            self.assertIsNotNone(bridge._policy)
            self.assertIsNotNone(bridge._policy.verifier)
            strict = bridge._coordinator.dispatch(job(JobPhase.COMPLETE, params={}), CellState.READY, MachineState.RUNNING)
            self.assertFalse(strict.accepted)
            key.write_text("short", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_bridge(load_service_config(path), SpotSessionConfig())


class RemoteSwitchTests(unittest.TestCase):
    """The switches of Server Admin only tighten what the host's own configuration says."""

    @staticmethod
    def bridge(policy, coordinator=None) -> DroidMqttBridge:
        bridge = DroidMqttBridge(coordinator or DroidCoordinator(), lambda: CellState.READY, None, global_stop=GlobalStopGuard(GlobalStopSettings(enabled=False)), policy=policy)
        bridge.remote_settings = True
        return bridge

    @staticmethod
    def apply(bridge: DroidMqttBridge, settings: dict) -> dict:
        from unittest import mock

        with mock.patch("hydra_umc_bridge_droids.mqtt_transport.parse_remote_settings", return_value=settings):
            return bridge.note_remote_settings(b"{}")

    def test_the_known_switches_are_listed(self) -> None:
        from hydra_umc_bridge_droids.remote_settings import SWITCHES

        self.assertIn("confirmationRequired", SWITCHES)
        self.assertIn("returnHomeAlways", SWITCHES)

    def test_the_confirmation_can_be_required_but_not_waived(self) -> None:
        loose = DroidPolicy(False, None)
        bridge = self.bridge(loose)
        self.apply(bridge, {"confirmationRequired": True})
        self.assertTrue(loose.confirmation_required)
        self.apply(bridge, {"confirmationRequired": False})
        self.assertTrue(loose.confirmation_required)

    def test_going_home_can_be_put_back_through_the_gate_but_not_taken_out_of_it(self) -> None:
        coordinator = DroidCoordinator()
        bridge = self.bridge(None, coordinator)
        self.apply(bridge, {"returnHomeAlways": True})
        self.assertTrue(coordinator.return_home_always)
        self.apply(bridge, {"returnHomeAlways": False})
        self.assertFalse(coordinator.return_home_always)
        self.assertFalse(coordinator.dispatch(job(JobPhase.COMPLETE, params={}), CellState.READY, MachineState.RUNNING).accepted)
        self.apply(bridge, {"returnHomeAlways": True})
        self.assertFalse(coordinator.return_home_always)
        # holding position stays available
        self.assertTrue(coordinator.dispatch(job(JobPhase.ABORT, params={}), CellState.FAULT, MachineState.FAULT).accepted)


if __name__ == "__main__":
    unittest.main()
