# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - tests of the switches announced by the server (no broker)
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The retained settings of the server: listened to only when the host allows it and holds the key, signed, current and not replayed, validated, and applied to the cut and to the global stop."""

import json
import os
import tempfile
import unittest
from types import SimpleNamespace

from hydra_umc_sdk.bridge_contract import CellState
from hydra_umc_sdk.global_stop import GlobalStopGuard, GlobalStopSettings
from hydra_umc_sdk.signed_commands import sign_command

from hydra_umc_bridge_droids import DroidCoordinator, SpotSessionConfig
from hydra_umc_bridge_droids.mqtt_transport import DroidMqttBridge, MessageDispatcher, _on_connected
from hydra_umc_bridge_droids.remote_settings import KEY_ENVIRONMENT, REMOTE_ENVIRONMENT, SETTINGS_TOPIC, SettingsVerifier, parse_remote_settings, remote_settings_allowed

from test_spot_session import make_session


KEY = b"k" * 64
NOW_MS = 1_800_000_000_000
_counter = [1000]


def message(*, key=KEY, seq=None, issued=NOW_MS, expires=60_000, **settings):
    """A settings message signed like the server signs it; `seq` counts up unless given."""
    if seq is None:
        _counter[0] += 1
        seq = _counter[0]
    body = sign_command(SETTINGS_TOPIC, {"schema": 2, "settings": settings, "seq": seq}, key, now_ms=issued, expires_in_ms=expires)
    return json.dumps(body).encode()


def verifier(key=KEY, now_ms=NOW_MS):
    return SettingsVerifier(key, clock=lambda: now_ms / 1000)


def make_bridge(remote, global_stop=False, config=None, key=KEY):
    session, _, _, _ = make_session(config)
    assert session.bring_up().ok
    bridge = DroidMqttBridge(
        DroidCoordinator(), lambda: CellState.READY, session, global_stop=GlobalStopGuard(GlobalStopSettings(enabled=global_stop)), remote_settings=remote, settings_verifier=verifier(key)
    )
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
        self.assertEqual(parse_remote_settings(message(globalStop=True, cutOnGlobalStop=False, other=1), verifier()), {"globalStop": True, "cutOnGlobalStop": False})

    def test_anything_else_changes_nothing(self):
        for payload in (b"", b"not json", b"[]", b'{"schema":2,"settings":{"globalStop":true}}', b'{"schema":1}', message(globalStop="yes"), b" " * 5000):
            self.assertIsNone(parse_remote_settings(payload, verifier()), payload[:30])

    def test_an_unsigned_or_old_format_message_is_refused(self):
        for payload in (json.dumps({"schema": 1, "settings": {"globalStop": True}}).encode(), json.dumps({"schema": 2, "settings": {"globalStop": True}, "seq": 1}).encode()):
            self.assertIsNone(parse_remote_settings(payload, verifier()))

    def test_without_a_verifier_nothing_is_accepted(self):
        self.assertIsNone(parse_remote_settings(message(globalStop=True)))

    def test_a_signature_made_with_another_key_or_altered_afterwards_is_refused(self):
        self.assertIsNone(parse_remote_settings(message(key=b"z" * 64, globalStop=True), verifier()))
        forged = json.loads(message(cutOnGlobalStop=True))
        forged["settings"]["cutOnGlobalStop"] = False
        self.assertIsNone(parse_remote_settings(json.dumps(forged).encode(), verifier()))

    def test_an_expired_message_is_refused_and_a_fresh_one_is_accepted(self):
        self.assertIsNone(parse_remote_settings(message(globalStop=True, expires=1_000), verifier(now_ms=NOW_MS + 5_000)))
        self.assertEqual(parse_remote_settings(message(globalStop=True, expires=60_000), verifier(now_ms=NOW_MS + 5_000)), {"globalStop": True})

    def test_a_message_from_the_future_or_asking_too_long_a_life_is_refused(self):
        self.assertIsNone(parse_remote_settings(message(globalStop=True, issued=NOW_MS + 60_000), verifier()))
        self.assertIsNone(parse_remote_settings(message(globalStop=True, expires=3_600_000), verifier()))

    def test_an_older_message_is_a_replay_and_the_same_one_again_changes_nothing_new(self):
        judge = verifier()
        newer, older = message(seq=50, globalStop=True), message(seq=49, globalStop=False)
        self.assertEqual(parse_remote_settings(newer, judge), {"globalStop": True})
        self.assertIsNone(parse_remote_settings(older, judge))
        self.assertEqual(parse_remote_settings(newer, judge), {"globalStop": True})

    def test_the_key_file_is_the_only_source_of_the_key(self):
        self.assertFalse(SettingsVerifier.from_environment({}).usable)
        self.assertFalse(SettingsVerifier.from_environment({KEY_ENVIRONMENT: os.path.join(tempfile.gettempdir(), "no-such-key-file")}).usable)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "settings.key")
            with open(path, "wb") as handle:
                handle.write(KEY + b"\n")
            os.chmod(path, 0o600)
            self.assertTrue(SettingsVerifier.from_environment({KEY_ENVIRONMENT: path}).usable)
            with open(path, "wb") as handle:
                handle.write(b"short")
            self.assertFalse(SettingsVerifier.from_environment({KEY_ENVIRONMENT: path}).usable)


class ApplyTests(unittest.TestCase):
    def test_without_the_host_switch_nothing_is_applied(self):
        bridge, session = make_bridge(remote=False)
        self.assertEqual(bridge.note_remote_settings(message(cutOnGlobalStop=False, globalStop=True)), {})
        self.assertTrue(session.config.cut_on_global_stop)
        self.assertFalse(bridge.global_stop.enabled)

    def test_with_the_host_switch_but_no_key_nothing_is_followed(self):
        bridge, session = make_bridge(remote=True, key=None)
        self.assertFalse(bridge.remote_settings)
        self.assertEqual(bridge.note_remote_settings(message(cutOnGlobalStop=False)), {})
        self.assertTrue(session.config.cut_on_global_stop)
        self.assertIsNone(_on_connected(bridge))

    def test_a_replayed_message_does_not_undo_a_newer_one(self):
        bridge, session = make_bridge(remote=True)
        self.assertEqual(bridge.note_remote_settings(message(seq=10, cutOnGlobalStop=False)), {"cutOnGlobalStop": False})
        self.assertEqual(bridge.note_remote_settings(message(seq=9, cutOnGlobalStop=True)), {})
        self.assertFalse(session.config.cut_on_global_stop)

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
