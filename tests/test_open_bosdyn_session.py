# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - the real-session factory and the keep-alive loop of the MQTT service, against a fake vendor library
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""open_bosdyn_session builds the adapters of the session on top of the vendor library; here that library is a small fake, so the wiring is checked
without a Spot and without the library installed. The keep-alive thread and the shutdown of run_forever are checked with a fake MQTT client."""

import sys
import threading
import types
import unittest
from unittest import mock

from hydra_umc_bridge_droids import mqtt_transport
from hydra_umc_bridge_droids.spot_session import SpotSession, SpotSessionConfig, open_bosdyn_session


class FakeEndpoint:
    def __init__(self, client, name, timeout):
        self.client, self.name, self.timeout, self.simple = client, name, timeout, False

    def force_simple_setup(self):
        self.simple = True


class FakeEstopKeepAlive:
    def __init__(self, endpoint):
        self.endpoint, self.stopped, self.allowed = endpoint, False, False
        self.status_queue = mock.Mock()
        self.status_queue.empty.return_value = True

    def stop(self):
        self.stopped = True

    def allow(self):
        self.allowed = True


class FakeLeaseKeepAlive:
    def __init__(self, client, must_acquire, return_at_exit):
        self.client, self.must_acquire, self.return_at_exit = client, must_acquire, return_at_exit
        self.alive, self.down = True, False

    def is_alive(self):
        return self.alive

    def shutdown(self):
        self.down = True


class FakeRobot:
    def __init__(self):
        self.powered, self.auth, self.synced, self.power_calls = False, None, False, []
        self.time_sync = types.SimpleNamespace(wait_for_sync=self._sync)

    def _sync(self):
        self.synced = True

    def authenticate(self, username, password):
        self.auth = (username, password)

    def ensure_client(self, name):
        return types.SimpleNamespace(name=name, get_robot_state=lambda: "state-message")

    def power_on(self, timeout_sec):
        self.power_calls.append(("on", timeout_sec))
        self.powered = True

    def power_off(self, cut_immediately, timeout_sec):
        self.power_calls.append(("off", cut_immediately, timeout_sec))
        self.powered = False

    def is_powered_on(self):
        return self.powered


def fake_vendor_modules(robot):
    def create_robot(hostname):
        robot.hostname = hostname
        return robot

    sdk = types.SimpleNamespace(create_robot=create_robot)
    estop = types.ModuleType("bosdyn.client.estop")
    estop.EstopClient = types.SimpleNamespace(default_service_name="estop")
    estop.EstopEndpoint = FakeEndpoint
    estop.EstopKeepAlive = FakeEstopKeepAlive
    lease = types.ModuleType("bosdyn.client.lease")
    lease.LeaseClient = types.SimpleNamespace(default_service_name="lease")
    lease.LeaseKeepAlive = FakeLeaseKeepAlive
    robot_state = types.ModuleType("bosdyn.client.robot_state")
    robot_state.RobotStateClient = types.SimpleNamespace(default_service_name="state")
    client = types.ModuleType("bosdyn.client")
    client.create_standard_sdk = lambda name: sdk
    client.estop, client.lease = estop, lease
    package = types.ModuleType("bosdyn")
    package.client = client
    json_format = types.ModuleType("google.protobuf.json_format")
    json_format.MessageToDict = lambda message, preserving_proto_field_name: {"battery": message, "preserved": preserving_proto_field_name}
    protobuf = types.ModuleType("google.protobuf")
    protobuf.json_format = json_format
    google = types.ModuleType("google")
    google.protobuf = protobuf
    return {
        "bosdyn": package, "bosdyn.client": client, "bosdyn.client.estop": estop, "bosdyn.client.lease": lease,
        "bosdyn.client.robot_state": robot_state, "google": google, "google.protobuf": protobuf, "google.protobuf.json_format": json_format,
    }


class OpenSessionTests(unittest.TestCase):
    def setUp(self):
        self.robot = FakeRobot()
        patcher = mock.patch.dict(sys.modules, fake_vendor_modules(self.robot))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_robot_is_authenticated_and_its_clock_synchronised(self):
        session = open_bosdyn_session("spot.local", "operator", "pass")
        self.assertIsInstance(session, SpotSession)
        self.assertEqual((self.robot.hostname, self.robot.auth, self.robot.synced), ("spot.local", ("operator", "pass"), True))

    def test_the_estop_endpoint_uses_the_configured_timeout_and_is_cut_on_request(self):
        session = open_bosdyn_session("h", "u", "p", SpotSessionConfig(estop_timeout_s=7.5))
        self.assertFalse(session.estop.check_in())  # nothing registered yet
        session.estop.register()
        endpoint = session.estop.keep_alive.endpoint
        self.assertEqual((endpoint.timeout, endpoint.simple, endpoint.name), (7.5, True, "hydra-umc-bridge-droids"))
        self.assertTrue(session.estop.check_in())
        session.estop.keep_alive.status_queue.empty.return_value = False
        self.assertFalse(session.estop.check_in())  # a message in the queue means the endpoint is not healthy
        session.estop.allow()
        self.assertTrue(session.estop.keep_alive.allowed)
        session.estop.cut()
        self.assertTrue(session.estop.keep_alive.stopped)

    def test_cutting_or_allowing_before_registering_does_nothing_and_does_not_fail(self):
        session = open_bosdyn_session("h", "u", "p")
        session.estop.cut()
        session.estop.allow()
        self.assertIsNone(session.estop.keep_alive)

    def test_the_lease_is_taken_for_good_and_given_back(self):
        session = open_bosdyn_session("h", "u", "p")
        self.assertFalse(session.lease.is_alive())
        session.lease.acquire()
        keep_alive = session.lease.keep_alive
        self.assertEqual((keep_alive.client.name, keep_alive.must_acquire, keep_alive.return_at_exit), ("lease", True, True))
        self.assertTrue(session.lease.is_alive())
        keep_alive.alive = False
        self.assertFalse(session.lease.is_alive())
        session.lease.release()
        self.assertTrue(keep_alive.down)

    def test_releasing_a_lease_never_taken_does_nothing(self):
        session = open_bosdyn_session("h", "u", "p")
        session.lease.release()
        self.assertIsNone(session.lease.keep_alive)

    def test_power_is_asked_with_the_timeout_and_the_answer_is_the_robot_state(self):
        session = open_bosdyn_session("h", "u", "p")
        self.assertTrue(session.power.power_on(12.0))
        self.assertTrue(session.power.power_off(5.0))
        self.assertEqual(self.robot.power_calls, [("on", 12.0), ("off", False, 5.0)])
        self.robot.power_off = lambda cut_immediately, timeout_sec: None  # a robot that stays powered
        self.robot.powered = True
        self.assertFalse(session.power.power_off(1.0))

    def test_the_robot_state_is_read_as_plain_data(self):
        session = open_bosdyn_session("h", "u", "p")
        state = session.state_reader.get_robot_state()
        self.assertEqual(state, {"battery": "state-message", "preserved": True})

    def test_the_default_configuration_is_used_when_none_is_given(self):
        self.assertEqual(open_bosdyn_session("h", "u", "p").config, SpotSessionConfig())


class MissingLibraryTests(unittest.TestCase):
    def test_a_missing_vendor_library_is_a_clear_error(self):
        with mock.patch.dict(sys.modules, {"bosdyn": None, "bosdyn.client": None}):
            with self.assertRaises(RuntimeError) as caught:
                open_bosdyn_session("h", "u", "p")
        self.assertIn("bosdyn-client is not installed", str(caught.exception))


class KeepAliveTests(unittest.TestCase):
    """run_forever ticks the session while the client loop runs, and stops the thread and the dispatcher when the loop ends."""

    def _bridge(self, ready=True):
        session = mock.Mock()
        session.ready = ready
        session.config = SpotSessionConfig(tick_interval_s=0.01)
        bridge = mock.Mock()
        bridge.session = session
        return bridge, session

    def _run(self, bridge, loop):
        client = mock.Mock()
        client.loop_forever.side_effect = loop
        with mock.patch.object(mqtt_transport, "open_bridge_client", return_value=client), mock.patch.object(mqtt_transport, "MessageDispatcher") as dispatcher:
            self.dispatcher = dispatcher.return_value
            mqtt_transport.run_forever(bridge, "broker.local")

    def test_a_ready_session_is_ticked_while_the_loop_runs(self):
        bridge, session = self._bridge(ready=True)
        ticked = threading.Event()
        session.tick.side_effect = ticked.set
        self._run(bridge, lambda: self.assertTrue(ticked.wait(5)))
        self.dispatcher.close.assert_called_once_with(wait=False)

    def test_a_session_that_is_not_ready_is_not_ticked(self):
        bridge, session = self._bridge(ready=False)
        self._run(bridge, lambda: threading.Event().wait(0.1))
        session.tick.assert_not_called()

    def test_the_dispatcher_is_closed_even_when_the_loop_raises(self):
        bridge, _ = self._bridge()

        def boom():
            raise OSError("connection lost")

        with self.assertRaises(OSError):
            self._run(bridge, boom)
        self.dispatcher.close.assert_called_once_with(wait=False)

    def test_a_password_without_a_username_is_refused_before_anything_starts(self):
        bridge, _ = self._bridge()
        with self.assertRaises(ValueError):
            mqtt_transport.run_forever(bridge, "broker.local", password="x")

    def test_a_bridge_without_a_session_still_runs(self):
        bridge = mock.Mock()
        bridge.session = None
        self._run(bridge, lambda: None)
        self.dispatcher.close.assert_called_once_with(wait=False)


if __name__ == "__main__":
    unittest.main()
