# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - MQTT transport tests (no broker)
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Topic routing, the shared intake, and the cut of the robot on a global stop, against the Spot fakes."""

import json
import unittest
from types import SimpleNamespace

from hydra_umc_sdk.bridge_contract import CellState
from hydra_umc_sdk.global_stop import GlobalStopGuard, GlobalStopSettings

from hydra_umc_bridge_droids import DroidCoordinator, SpotSessionConfig
from hydra_umc_bridge_droids.mqtt_transport import TOPIC_PREFIX, DroidMqttBridge, MessageDispatcher

from test_spot_session import make_session


def job(phase="PREPARE", key="k1", **parameters):
    return json.dumps(
        {"job_id": "j", "phase": phase, "idempotency_key": key, "machine_state": "IDLE", "parameters": parameters or {"x": "1", "y": "2"}}
    ).encode()


def make_bridge(enabled=True, config=None, with_session=True, cell=CellState.READY):
    session = None
    if with_session:
        session, _, parts, _ = make_session(config)
        assert session.bring_up().ok
    guard = GlobalStopGuard(GlobalStopSettings(enabled=enabled))
    bridge = DroidMqttBridge(DroidCoordinator(), lambda: cell, session, global_stop=guard)
    return bridge, session


def answer(publishes):
    return json.loads(publishes[0].payload)


class RoutingTests(unittest.TestCase):
    def test_status_publishes_the_retained_state(self):
        bridge, session = make_bridge()
        out = bridge.handle_message(TOPIC_PREFIX + "cmd/status", b"")
        self.assertTrue(out[0].retain)
        body = answer(out)
        self.assertTrue(body["session_ready"])
        self.assertEqual(body["global_stop"], "UNKNOWN")

    def test_retained_and_foreign_topics_are_ignored(self):
        bridge, _ = make_bridge()
        self.assertEqual(bridge.handle_message(TOPIC_PREFIX + "cmd/estop", b"", retained=True), [])
        self.assertEqual(bridge.handle_message("other/cmd/estop", b""), [])

    def test_a_job_is_gated_never_executed_and_a_repeat_is_not_run_twice(self):
        bridge, _ = make_bridge()
        first = answer(bridge.handle_message(TOPIC_PREFIX + "cmd/job", job()))
        self.assertFalse(first["executed"])
        second = answer(bridge.handle_message(TOPIC_PREFIX + "cmd/job", job()))
        self.assertFalse(second["allowed"])

    def test_a_malformed_job_is_an_answer_not_an_exception(self):
        bridge, _ = make_bridge()
        self.assertFalse(answer(bridge.handle_message(TOPIC_PREFIX + "cmd/job", b"{not json"))["allowed"])
        self.assertFalse(answer(bridge.handle_message(TOPIC_PREFIX + "cmd/job", b"[1]"))["allowed"])

    def test_an_oversized_payload_is_refused(self):
        bridge, _ = make_bridge()
        self.assertFalse(answer(bridge.handle_message(TOPIC_PREFIX + "cmd/job", b"x" * 20000))["allowed"])

    def test_estop_cuts_the_session(self):
        bridge, session = make_bridge()
        body = answer(bridge.handle_message(TOPIC_PREFIX + "cmd/estop", b""))
        self.assertTrue(body["executed"])
        self.assertFalse(session.ready)

    def test_estop_without_a_session_says_so(self):
        bridge, _ = make_bridge(with_session=False)
        self.assertFalse(answer(bridge.handle_message(TOPIC_PREFIX + "cmd/estop", b""))["allowed"])

    def test_hold_is_never_gated(self):
        bridge, _ = make_bridge(cell=CellState.SAFE_STOP)
        bridge.note_global_stop(b'{"state":"SAFE_STOP"}')
        self.assertTrue(answer(bridge.handle_message(TOPIC_PREFIX + "cmd/hold", b""))["allowed"])


class GlobalStopTests(unittest.TestCase):
    def test_safe_stop_cuts_the_keep_alive_and_refuses_jobs(self):
        bridge, session = make_bridge()
        bridge.note_global_stop(b'{"state":"SAFE_STOP"}')
        self.assertFalse(session.ready)
        self.assertIn("global stop", session.cut_reason)
        self.assertFalse(session.tick().ok)
        self.assertFalse(answer(bridge.handle_message(TOPIC_PREFIX + "cmd/job", job(key="k2")))["allowed"])

    def test_ready_after_a_stop_does_not_bring_the_robot_back(self):
        bridge, session = make_bridge()
        bridge.note_global_stop(b'{"state":"SAFE_STOP"}')
        bridge.note_global_stop(b'{"state":"READY"}')
        self.assertFalse(session.ready)

    def test_the_cut_is_a_setting_of_the_configuration(self):
        bridge, session = make_bridge(config=SpotSessionConfig(cut_on_global_stop=False))
        bridge.note_global_stop(b'{"state":"SAFE_STOP"}')
        self.assertTrue(session.ready)
        self.assertFalse(answer(bridge.handle_message(TOPIC_PREFIX + "cmd/job", job(key="k3")))["allowed"])

    def test_a_message_that_cannot_be_read_counts_as_a_stop(self):
        bridge, session = make_bridge()
        bridge.note_global_stop(b"garbage")
        self.assertFalse(session.ready)

    def test_with_the_switch_off_the_announcement_is_not_followed(self):
        bridge, session = make_bridge(enabled=False)
        self.assertEqual(bridge.note_global_stop(b'{"state":"SAFE_STOP"}'), "OFF")
        self.assertTrue(session.ready)
        # the gate may still refuse (motors off), but not because of the global stop
        self.assertNotIn("global stop", answer(bridge.handle_message(TOPIC_PREFIX + "cmd/job", job(key="k4")))["reason"])

    def test_the_dispatcher_reads_the_announcement_before_the_retained_check(self):
        bridge, session = make_bridge()
        dispatcher = MessageDispatcher(bridge)
        try:
            message = SimpleNamespace(topic=bridge.global_stop.topic, payload=b'{"state":"SAFE_STOP"}', retain=True)
            dispatcher.on_message(None, None, message)
        finally:
            dispatcher.close(wait=False)
        self.assertFalse(session.ready)


if __name__ == "__main__":
    unittest.main()
