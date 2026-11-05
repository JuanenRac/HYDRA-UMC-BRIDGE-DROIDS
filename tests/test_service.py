# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - service entry point tests (no broker, no robot)
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The configuration of the service: what it accepts, what it refuses, and that `--check` opens nothing."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from hydra_umc_bridge_droids.service import ConfigError, build_bridge, load_service_config, main
from hydra_umc_bridge_droids.spot_session import SpotSessionConfig

REPO = Path(__file__).resolve().parent.parent


def write(directory: str, name: str, body: object) -> str:
    path = Path(directory) / name
    path.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    return str(path)


class ServiceConfigTests(unittest.TestCase):
    def test_the_shipped_configuration_is_valid_and_has_no_robot(self):
        config = load_service_config(REPO / "config" / "bridge.json")
        self.assertEqual(config.spot.host, "")
        self.assertEqual(config.mqtt.port, 1883)

    def test_a_missing_file_gives_the_defaults(self):
        self.assertEqual(load_service_config("no/such/file.json").spot.host, "")

    def test_an_unknown_key_or_a_wrong_type_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            for body in ({"mqt": {}}, {"mqtt": {"hostt": "x"}}, {"mqtt": {"port": "1883"}}, {"mqtt": {"port": True}}, {"mqtt": []}, {"session_config": 3}, []):
                with self.subTest(body=body), self.assertRaises(ConfigError):
                    load_service_config(write(d, "c.json", body))

    def test_a_broken_file_and_out_of_range_values_are_errors(self):
        with tempfile.TemporaryDirectory() as d:
            for body in ("{not json", {"mqtt": {"port": 0}}, {"mqtt": {"host": ""}}, {"mqtt": {"max_connect_attempts": 0}}):
                with self.subTest(body=body), self.assertRaises(ConfigError):
                    load_service_config(write(d, "c.json", body))

    def test_a_robot_needs_its_user_and_a_password_file(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ConfigError):
                load_service_config(write(d, "c.json", {"spot": {"host": "192.0.2.5"}}))
            ok = load_service_config(write(d, "c.json", {"spot": {"host": "192.0.2.5", "username": "u", "password_file": "p"}}))
            self.assertEqual(ok.spot.host, "192.0.2.5")


class ServiceBehaviourTests(unittest.TestCase):
    def test_a_bridge_without_a_robot_has_no_session(self):
        bridge = build_bridge(load_service_config(None), SpotSessionConfig())
        self.assertIsNone(bridge.session)

    def test_a_missing_password_file_stops_before_anything_is_opened(self):
        with tempfile.TemporaryDirectory() as d:
            path = write(d, "c.json", {"spot": {"host": "192.0.2.5", "username": "u", "password_file": str(Path(d) / "absent")}})
            with self.assertRaises(ConfigError):
                build_bridge(load_service_config(path), SpotSessionConfig())

    def test_check_validates_and_opens_nothing(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--config", str(REPO / "config" / "bridge.json"), "--check"])
        self.assertEqual(code, 0)
        self.assertIn("CONFIG=PASS", out.getvalue())

    def test_check_with_a_bad_file_exits_2(self):
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--config", write(d, "c.json", {"bad": 1}), "--check"]), 2)


if __name__ == "__main__":
    unittest.main()
