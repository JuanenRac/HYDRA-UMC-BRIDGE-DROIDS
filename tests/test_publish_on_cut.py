# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - tests of the publication of the state at every cut (no broker)
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The retained state of the droid bridge is published at the moment of EVERY cut (an operator request, the global stop, a lost link), not only when a status or an e-stop
command is handled, so the safety zones service that reads it learns of the cut at once. Nothing here uses a broker: the publisher is a list."""

import json
import unittest

from hydra_umc_sdk.bridge_contract import CellState
from hydra_umc_sdk.global_stop import GlobalStopGuard, GlobalStopSettings

from hydra_umc_bridge_droids import DroidCoordinator
from hydra_umc_bridge_droids.mqtt_transport import STATE_TOPIC, DroidMqttBridge

from test_spot_session import make_session


def make_bridge(with_session=True):
    session = None
    if with_session:
        session, _, _, _ = make_session()
        assert session.bring_up().ok
    bridge = DroidMqttBridge(DroidCoordinator(), lambda: CellState.READY, session, global_stop=GlobalStopGuard(GlobalStopSettings(enabled=True)))
    sent: list[tuple[str, dict]] = []
    bridge.publisher = lambda topic, payload: sent.append((topic, json.loads(payload)))
    return bridge, session, sent


class PublishOnCutTests(unittest.TestCase):
    def test_a_cut_from_outside_publishes_the_state_at_once(self):
        bridge, session, sent = make_bridge()
        session.cut("zone violation")
        self.assertEqual(len(sent), 1)
        topic, state = sent[0]
        self.assertEqual(topic, STATE_TOPIC)
        self.assertEqual((state["session_ready"], state["cut_reason"]), (False, "zone violation"))

    def test_the_announcement_of_the_global_stop_that_cuts_the_session_publishes_it(self):
        bridge, session, sent = make_bridge()
        bridge.note_global_stop(json.dumps({"state": "SAFE_STOP"}).encode())
        self.assertTrue(sent and sent[-1][1]["cut_reason"].startswith("global stop announced"))

    def test_the_cut_by_an_operator_over_mqtt_is_published_once_by_the_hook_and_answered(self):
        bridge, session, sent = make_bridge()
        publishes = bridge.handle_message(f"{STATE_TOPIC.rsplit('/', 1)[0]}/cmd/estop", b"")
        self.assertEqual(sent[0][1]["cut_reason"], "cut by an operator request over MQTT")
        self.assertTrue(any(p.topic == STATE_TOPIC for p in publishes))  # the answer still carries the state

    def test_a_cut_without_a_connection_publishes_nothing_and_the_tick_publishes_it_later(self):
        bridge, session, sent = make_bridge()
        bridge.publisher = None
        session.cut("lost")
        self.assertEqual(sent, [])
        self.assertFalse(bridge.publish_state())
        later: list[dict] = []
        bridge.publisher = lambda topic, payload: later.append(json.loads(payload))
        self.assertTrue(bridge.publish_state_if_changed())
        self.assertEqual(later[0]["cut_reason"], "lost")
        self.assertFalse(bridge.publish_state_if_changed(), "nothing changed since")

    def test_a_publisher_that_fails_is_tried_again_and_never_undoes_the_cut(self):
        bridge, session, _ = make_bridge()
        failures = [True]

        def flaky(topic, payload):
            if failures[0]:
                raise OSError("broker gone")

        bridge.publisher = flaky
        session.cut("cut")
        self.assertEqual(session.cut_reason, "cut")
        self.assertFalse(session.ready)
        self.assertTrue(bridge.publish_state_if_changed() is False)  # still failing
        failures[0] = False
        self.assertTrue(bridge.publish_state_if_changed())

    def test_a_hook_that_raises_does_not_stop_the_cut(self):
        session, _, _, _ = make_session()
        self.assertTrue(session.bring_up().ok)

        def broken(reason):
            raise RuntimeError("no")

        session.on_cut = broken
        session.cut("cut")
        self.assertEqual(session.cut_reason, "cut")
        self.assertFalse(session.ready)

    def test_the_first_publication_after_a_reconnect_and_a_lost_link_without_a_cut(self):
        bridge, session, sent = make_bridge()
        self.assertTrue(bridge.publish_state_if_changed())  # nothing was published yet: the retained state of a ready session
        self.assertEqual(sent[-1][1]["session_ready"], True)
        self.assertFalse(bridge.publish_state_if_changed())
        session.cut("again")
        self.assertEqual(sent[-1][1]["cut_reason"], "again")

    def test_without_a_session_nothing_is_published_and_nothing_is_hooked(self):
        bridge, session, sent = make_bridge(with_session=False)
        self.assertIsNone(session)
        self.assertTrue(bridge.publish_state_if_changed())  # the state of no session: not ready, no reason
        self.assertEqual((sent[-1][1]["session_ready"], sent[-1][1]["cut_reason"]), (False, ""))
        self.assertFalse(bridge.publish_state_if_changed())


if __name__ == "__main__":
    unittest.main()
