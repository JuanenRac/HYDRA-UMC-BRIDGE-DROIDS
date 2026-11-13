# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - service entry point (python -m hydra_umc_bridge_droids)
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Start the droid bridge as a service: read the configuration, optionally bring up a Spot, then serve the MQTT topics.

Every value comes from `config/bridge.json` (broker, client id, connection retries, and the Spot to open) and `config/spot_session.json` (the session); the two
secrets are never in a file of the repository or on the command line: the passwords are read from the files the configuration names. Without a `spot.host` the
bridge only gates jobs and has nothing to cut. With one, the bring-up must succeed or the service stops with a non-zero status (the service manager restarts it).
`--check` reads and validates the configuration and exits without opening anything. Nothing here has run against a real broker or a real Spot.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field, fields
from pathlib import Path

from hydra_umc_sdk.bridge_contract import CellState

from .coordinator import DroidCoordinator
from .droid_policy import DroidPolicy
from .human_confirmation import ConfirmationVerifier, load_key
from .mqtt_transport import DroidMqttBridge, run_forever
from .spot_session import SpotSessionConfig, load_session_config, open_bosdyn_session

_LOG = logging.getLogger(__name__)
CONFIG_ENVIRONMENT = "HYDRA_UMC_DROIDS_CONFIG"
DEFAULT_CONFIG_PATH = "config/bridge.json"
DEFAULT_SESSION_PATH = "config/spot_session.json"


class ConfigError(ValueError):
    """The service configuration cannot be used (a mistyped key is an error, never a silent default)."""


@dataclass(frozen=True)
class MqttConfig:
    host: str = "127.0.0.1"
    port: int = 1883
    client_id: str = "hydra-umc-bridge-droids"
    username: str = ""
    password_file: str = ""
    max_connect_attempts: int = 5
    connect_retry_delay_seconds: float = 2.0


@dataclass(frozen=True)
class SpotConfig:
    host: str = ""  # empty: no robot, the bridge only gates jobs
    username: str = ""
    password_file: str = ""


@dataclass(frozen=True)
class PolicyConfig:
    # a job that moves the droid must carry a confirmation of an operator signed by the server, valid once; on by default (see droid_policy.py)
    confirmation_required: bool = True
    confirmation_key_file: str = ""
    confirmation_max_ttl_s: float = 120.0
    confirmation_max_clock_skew_s: float = 5.0
    # going home is forwarded whatever the machine state says (like return to launch in BRIDGE-UAV); false makes it go through the gate like any other action
    return_home_always: bool = True


@dataclass(frozen=True)
class ServiceConfig:
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    spot: SpotConfig = field(default_factory=SpotConfig)
    session_config: str = DEFAULT_SESSION_PATH
    policy: PolicyConfig = field(default_factory=PolicyConfig)


def _section(raw: object, kind: type, name: str):
    if raw is None:
        return kind()
    if not isinstance(raw, dict):
        raise ConfigError(f"'{name}' must be a JSON object")
    known = {item.name for item in fields(kind)}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ConfigError(f"unknown keys in '{name}': {', '.join(unknown)}")
    defaults = kind()
    for key, value in raw.items():
        wanted = type(getattr(defaults, key))
        if wanted is float and isinstance(value, int) and not isinstance(value, bool):
            continue
        if not isinstance(value, wanted) or (wanted is int and isinstance(value, bool)):
            raise ConfigError(f"'{name}.{key}' must be a {wanted.__name__}")
    return kind(**raw)


def load_service_config(path: str | Path | None) -> ServiceConfig:
    """Read the service configuration; no file gives the defaults (no robot, a local broker)."""

    if path is None or not Path(path).is_file():
        return ServiceConfig()
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ConfigError(f"cannot read {path}: {error}") from error
    if not isinstance(raw, dict):
        raise ConfigError("the configuration must be a JSON object")
    unknown = sorted(set(raw) - {"mqtt", "spot", "session_config", "policy"})
    if unknown:
        raise ConfigError(f"unknown keys: {', '.join(unknown)}")
    session_config = raw.get("session_config", DEFAULT_SESSION_PATH)
    if not isinstance(session_config, str):
        raise ConfigError("'session_config' must be a string")
    config = ServiceConfig(_section(raw.get("mqtt"), MqttConfig, "mqtt"), _section(raw.get("spot"), SpotConfig, "spot"), session_config, _section(raw.get("policy"), PolicyConfig, "policy"))
    if not config.mqtt.host or not 0 < config.mqtt.port < 65536:
        raise ConfigError("'mqtt.host' and 'mqtt.port' must name a broker")
    if config.mqtt.max_connect_attempts < 1 or config.mqtt.connect_retry_delay_seconds < 0:
        raise ConfigError("'mqtt' connection retries must be at least 1 attempt and a delay of 0 or more")
    policy = config.policy
    if not (0 < policy.confirmation_max_ttl_s <= 3600 and 0 < policy.confirmation_max_clock_skew_s <= 60):
        raise ConfigError("'policy' confirmation lifetime must be above 0 and at most 3600 s, and the clock skew above 0 and at most 60 s")
    if config.spot.host and not (config.spot.username and config.spot.password_file):
        raise ConfigError("'spot.host' needs 'spot.username' and 'spot.password_file'")
    return config


def _read_secret(path: str, what: str) -> str:
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ConfigError(f"cannot read the {what} file: {error.strerror or error}") from error
    if not value:
        raise ConfigError(f"the {what} file is empty")
    return value


def build_bridge(config: ServiceConfig, session_config: SpotSessionConfig) -> DroidMqttBridge:
    """The bridge, with a brought-up Spot session when the configuration names one (raises RuntimeError when the bring-up fails)."""

    session = None
    if config.spot.host:
        password = _read_secret(config.spot.password_file, "Spot password")
        session = open_bosdyn_session(config.spot.host, config.spot.username, password, session_config)
        result = session.bring_up()
        if not result.ok:
            raise RuntimeError(f"the Spot bring-up failed: {result.reason}")

    def cell_state() -> CellState:
        # without a robot the bridge only gates and the job carries its own machine state; with one, a cut session means the cell is faulted
        return CellState.READY if session is None or session.ready else CellState.FAULT

    policy = config.policy
    verifier = None
    if policy.confirmation_required and policy.confirmation_key_file.strip():
        verifier = ConfirmationVerifier(load_key(policy.confirmation_key_file), max_ttl_s=policy.confirmation_max_ttl_s, max_clock_skew_s=policy.confirmation_max_clock_skew_s)
    return DroidMqttBridge(DroidCoordinator(return_home_always=policy.return_home_always), cell_state, session, policy=DroidPolicy(policy.confirmation_required, verifier))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hydra_umc_bridge_droids", description="HYDRA-UMC droid bridge service")
    parser.add_argument("--config", default=os.environ.get(CONFIG_ENVIRONMENT, DEFAULT_CONFIG_PATH), help=f"configuration file (default: ${CONFIG_ENVIRONMENT} or {DEFAULT_CONFIG_PATH})")
    parser.add_argument("--check", action="store_true", help="read and validate the configuration, then exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        config = load_service_config(args.config)
        session_config = load_session_config(config.session_config)
        password = _read_secret(config.mqtt.password_file, "MQTT password") if config.mqtt.password_file else None
        if args.check:
            print(f"CONFIG=PASS {args.config}")
            return 0
        bridge = build_bridge(config, session_config)
    except ValueError as error:  # ConfigError is a ValueError
        print(f"hydra-umc-bridge-droids: configuration error: {error}", file=sys.stderr)
        return 2
    except RuntimeError as error:
        print(f"hydra-umc-bridge-droids: {error}", file=sys.stderr)
        return 3
    mqtt = config.mqtt
    # Restart=on-failure: a non-zero exit when the loop ends brings the service back
    try:
        run_forever(
            bridge,
            mqtt.host,
            mqtt.port,
            mqtt.client_id,
            max_connect_attempts=mqtt.max_connect_attempts,
            connect_retry_delay_seconds=mqtt.connect_retry_delay_seconds,
            username=mqtt.username or None,
            password=password,
        )
    except Exception:  # noqa: BLE001
        _LOG.exception("the bridge stopped")
        return 1
    return 1


__all__ = ["ConfigError", "MqttConfig", "PolicyConfig", "ServiceConfig", "SpotConfig", "build_bridge", "load_service_config", "main"]
