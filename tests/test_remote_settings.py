# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - tests of the switches announced by the server (no broker)
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The retained settings of the server: listened to only when the host allows it, validated, and applied to the cut and to the global stop."""

import json
import unittest
from types import SimpleNamespace

from hydra_umc_sdk.bridge_contract import CellState
from hydra_umc_sdk.global_stop import GlobalStopGuard, GlobalStopSettings

from hydra_umc_bridge_droids import DroidCoordinator, SpotSessionConfig
from hydra_umc_bridge_droids.mqtt_transport import DroidMqttBridge, MessageDispatcher, _on_connected
from hydra_umc_bridge_droids.remote_settings import REMOTE_ENVIRONMENT, SETTINGS_TOPIC, parse_remote_settings, remote_settings_allowed

from test_spot_session import make_session


def message(**settings):
    return json.dumps({"schema": 1, "settings": settings}).encode()


def make_bridge(remote, global_stop=False, config=None):
    session, _, _, _ = make_session(config)
    assert session.bring_up().ok
    bridge = DroidMqttBridge(DroidCoordinator(), lambda: CellState.READY, session, global_stop=GlobalStopGuard(GlobalStopSettings(enabled=global_stop)), remote_settings=remote)
    return bridge, session


class FakeClient:
    def __init__(self):
        self.subscribed = []

    def subscribe(self, topic, qos=0):
        self.subscribed.append((topic, qos))


class ParseTests(unittest.TestCase):
    def test_the_host_allows_remote_settings_only_with_its_own_switch(self):
        self.assertFalse(remote_settings_allowed({}))
        self.assertFalse(remote_settings_allowed({REMOTE_ENVIRONMENT: "0"}))
        self.assertTrue(remote_settings_allowed({REMOTE_ENVIRONMENT: "1"}))

    def test_a_valid_message_gives_the_known_switches_and_ignores_the_rest(self):
        self.assertEqual(parse_remote_settings(message(globalStop=True, cutOnGlobalStop=False, other=1)), {"globalStop": True, "cutOnGlobalStop": False})

    def test_anything_else_changes_nothing(self):
        for payload in (b"", b"not json", b"[]", b'{"schema":2,"settings":{"globalStop":true}}', b'{"schema":1}', message(globalStop="yes"), b" " * 5000):
            self.assertIsNone(parse_remote_settings(payload), payload[:30])


class ApplyTests(unittest.TestCase):
    def test_without_the_host_switch_nothing_is_applied(self):
        bridge, session = make_bridge(remote=False)
        self.assertEqual(bridge.note_remote_settings(message(cutOnGlobalStop=False, globalStop=True)), {})
        self.assertTrue(session.config.cut_on_global_stop)
        self.assertFalse(bridge.global_stop.enabled)

    def test_the_cut_follows_the_server(self):
        bridge, session = make_bridge(remote=True)
        self.assertEqual(bridge.note_remote_settings(message(cutOnGlobalStop=False)), {"cutOnGlobalStop": False})
        self.assertFalse(session.config.cut_on_global_stop)
        bridge.note_remote_settings(message(cutOnGlobalStop=True))
        self.assertTrue(session.config.cut_on_global_stop)

    def test_the_global_stop_is_switched_on_and_followed_at_once(self):
        bridge, _ = make_bridge(remote=True)
        client = FakeClient()
        bridge.note_remote_settings(message(globalStop=True), client)
        self.assertTrue(bridge.global_stop.enabled)
        self.assertEqual(client.subscribed, [(bridge.global_stop.topic, 1)])
        bridge.note_remote_settings(message(globalStop=False), client)
        self.assertFalse(bridge.global_stop.enabled)

    def test_an_invalid_message_leaves_everything_as_it_was(self):
        bridge, session = make_bridge(remote=True)
        self.assertEqual(bridge.note_remote_settings(message(cutOnGlobalStop="no")), {})
        self.assertTrue(session.config.cut_on_global_stop)

    def test_the_dispatcher_reads_the_settings_before_the_retained_check_and_only_when_allowed(self):
        for remote, expected in ((True, False), (False, True)):
            bridge, session = make_bridge(remote=remote)
            dispatcher = MessageDispatcher(bridge)
            try:
                dispatcher.on_message(FakeClient(), None, SimpleNamespace(topic=SETTINGS_TOPIC, payload=message(cutOnGlobalStop=False), retain=True))
            finally:
                dispatcher.close(wait=False)
            self.assertEqual(session.config.cut_on_global_stop, expected)

    def test_the_settings_topic_is_subscribed_after_a_connect_only_when_allowed(self):
        allowed, _ = make_bridge(remote=True)
        client = FakeClient()
        _on_connected(allowed)(client)
        self.assertEqual(client.subscribed, [(SETTINGS_TOPIC, 1)])
        refused, _ = make_bridge(remote=False)
        self.assertIsNone(_on_connected(refused))
        stopping, _ = make_bridge(remote=False, global_stop=True)
        client = FakeClient()
        _on_connected(stopping)(client)
        self.assertEqual(client.subscribed, [(stopping.global_stop.topic, 1)])

    def test_a_cut_on_a_global_stop_obeys_the_value_in_force(self):
        bridge, session = make_bridge(remote=True, global_stop=True, config=SpotSessionConfig(cut_on_global_stop=True))
        bridge.note_remote_settings(message(cutOnGlobalStop=False))
        bridge.note_global_stop(b'{"state":"SAFE_STOP"}')
        self.assertTrue(session.ready)


if __name__ == "__main__":
    unittest.main()
