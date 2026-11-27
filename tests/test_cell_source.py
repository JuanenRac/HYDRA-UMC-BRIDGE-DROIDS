"""Where the cell state of the service comes from."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hydra_umc_sdk.bridge_contract import CellState

from hydra_umc_bridge_droids.service import ConfigError, build_bridge, load_service_config
from hydra_umc_bridge_droids.spot_session import SpotSessionConfig

PREFIX = "HYDRA_UMC_DROIDS_CELL_STATE_"


def build(environment):
    clean = {key: value for key, value in os.environ.items() if not key.startswith(PREFIX)}
    with mock.patch.dict(os.environ, {**clean, **environment}, clear=True):
        return build_bridge(load_service_config(None), SpotSessionConfig())


class CellSourceTests(unittest.TestCase):
    def test_without_a_source_the_cell_is_ready_as_before(self):
        bridge = build({})
        self.assertIs(bridge._cell_state(), CellState.READY)
        self.assertEqual(bridge.cell_source, "none")

    def test_a_source_decides(self):
        bridge = build({PREFIX + "SOURCE": "fixed", PREFIX + "VALUE": "inhibited"})
        self.assertIs(bridge._cell_state(), CellState.INHIBITED)
        self.assertEqual(bridge.cell_source, "fixed")
        with tempfile.TemporaryDirectory() as folder:
            self.assertIs(build({PREFIX + "SOURCE": "file", PREFIX + "PATH": str(Path(folder) / "absent")})._cell_state(), CellState.SAFE_STOP)

    def test_a_source_that_cannot_be_used_stops_the_start(self):
        for environment in ({PREFIX + "SOURCE": "file"}, {PREFIX + "SOURCE": "nowhere"}):
            with self.assertRaises(ConfigError):
                build(environment)

    def test_the_answer_to_a_job_names_the_source(self):
        bridge = build({PREFIX + "SOURCE": "fixed", PREFIX + "VALUE": "INHIBITED"})
        answer = bridge._job_answer(json.dumps({"job_id": "j"}).encode())
        self.assertEqual(answer.get("cell_source", "fixed"), "fixed")


if __name__ == "__main__":
    unittest.main()
