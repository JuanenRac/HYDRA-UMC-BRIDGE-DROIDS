# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - MQTT transport over HYDRA-UMC-MQTT-BROKER
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Reach the droid coordinator over the MQTT broker, and cut the robot when the installation stops.

Topics (under the `hydra/bridges/<name>/...` convention of the broker):
  hydra/bridges/droids/state              <- retained: the session (ready, why it was cut), the machine state the gate reads, the global stop
  hydra/bridges/droids/availability       <- "online" / "offline", retained (Last Will)
  hydra/bridges/droids/cmd/status         -> (empty) publish the state now
  hydra/bridges/droids/cmd/job            -> BridgeJob JSON; the shared intake and the gate answer, nothing is sent to the robot (plan only)
  hydra/bridges/droids/cmd/hold           -> (empty) hold position: always answered, never gated
  hydra/bridges/droids/cmd/estop          -> (empty) cut the robot (the software e-stop endpoint stops being checked in)
  hydra/bridges/droids/cmd/<verb>/result  <- one JSON answer per command

  hydra/bridges/droids/settings           -> retained, from the server: the switches of Server Admin (only listened to when HYDRA_UMC_DROIDS_REMOTE_SETTINGS=1)

The global stop is the shared one of the SDK (`hydra_umc_sdk.global_stop`, off by default). While it is on and the server announces `SAFE_STOP`, a job is refused
(an abort is let through) and, when `cut_on_global_stop` is true in the session configuration (the default), the Spot session is cut at the moment of the announcement:
the keep-alive of the software e-stop ends, which is what stops a Spot whose bridge is no longer allowed to move it. The robot is not brought back by `READY`: a cut
session is started again by the operator (a new bring-up).

`DroidMqttBridge.handle_message()` is a plain dispatcher and is tested without a broker; `run_forever()` is the only place that imports paho-mqtt (lazily).
"""

from __future__ import annotations

import dataclasses
import json
import logging
import threading
import time
from typing import Callable

from hydra_umc_sdk.bridge_contract import CellState, MachineState
from hydra_umc_sdk.bridge_transport import BridgeHardening, MqttPublish, hardening_from_environment, open_bridge_client
from hydra_umc_sdk.bridge_transport import MessageDispatcher as SharedMessageDispatcher
from hydra_umc_sdk.global_stop import STATE_READY, GlobalStopGuard, GlobalStopSettings

from .coordinator import DroidCoordinator
from .remote_settings import SETTINGS_TOPIC, parse_remote_settings, remote_settings_allowed
from .spot_session import SpotSession

TOPIC_PREFIX = "hydra/bridges/droids/"
AVAILABILITY_TOPIC = f"{TOPIC_PREFIX}availability"
STATE_TOPIC = f"{TOPIC_PREFIX}state"
GLOBAL_STOP_ENVIRONMENT_NAME = "DROIDS"
MAX_PAYLOAD_BYTES = 16 * 1024
RESULT_QOS = 1
STOP_VERBS = frozenset({"cmd/hold", "cmd/estop"})
MOVING_VERBS: frozenset[str] = frozenset()  # nothing here moves on its own: a job only asks the gate, and the stops are never refused

_LOG = logging.getLogger(__name__)


def _refusal(suffix: str, reason: str) -> list[MqttPublish]:
    parts = suffix.split("/")
    if len(parts) != 2 or parts[0] != "cmd":
        return []
    return [MqttPublish(f"{TOPIC_PREFIX}{suffix}/result", json.dumps({"allowed": False, "executed": False, "reason": reason}), qos=RESULT_QOS)]


class DroidMqttBridge:
    """Topic routing of the droid bridge; `session` is optional (without it the bridge only gates jobs and has nothing to cut)."""

    def __init__(
        self,
        coordinator: DroidCoordinator,
        cell_state: Callable[[], CellState],
        session: SpotSession | None = None,
        *,
        clock: Callable[[], float] = time.time,
        global_stop: GlobalStopGuard | GlobalStopSettings | None = None,
        remote_settings: bool | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._cell_state = cell_state
        self.session = session
        self._clock = clock
        if isinstance(global_stop, GlobalStopGuard):
            self.global_stop = global_stop
        elif global_stop is not None:
            self.global_stop = GlobalStopGuard(global_stop)
        else:
            self.global_stop = GlobalStopGuard.from_environment(GLOBAL_STOP_ENVIRONMENT_NAME)
        self.remote_settings = remote_settings_allowed() if remote_settings is None else bool(remote_settings)

    # -- the switches announced by the server ------------------------------
    def note_remote_settings(self, payload: bytes, client: object = None) -> dict[str, bool]:
        """Apply the switches of a settings message and return what was applied ({} when the host does not allow remote settings or the message is not valid)."""
        if not self.remote_settings:
            return {}
        found = parse_remote_settings(payload)
        if not found:
            return {}
        session = self.session
        if "cutOnGlobalStop" in found and session is not None:
            session.config = dataclasses.replace(session.config, cut_on_global_stop=found["cutOnGlobalStop"])
        if "globalStop" in found:
            settings = self.global_stop.settings
            self.global_stop.settings = dataclasses.replace(settings, enabled=found["globalStop"])
            if found["globalStop"] and client is not None:
                client.subscribe(self.global_stop.topic, qos=1)  # type: ignore[attr-defined]
        _LOG.info("remote settings applied: %s", ", ".join(f"{key}={value}" for key, value in sorted(found.items())))
        return found

    # -- the global stop -------------------------------------------------
    def note_global_stop(self, payload: bytes) -> str:
        """Feed the announcement of the server; on anything but READY, cut the session when the configuration says so. Returns the state read."""
        if not self.global_stop.enabled:
            return "OFF"  # the switch is off: the announcement is not followed, nothing is cut
        state = self.global_stop.observe(payload)
        session = self.session
        if state != STATE_READY and session is not None and session.config.cut_on_global_stop:
            session.cut(f"global stop announced ({state})")
        return state

    # -- state ------------------------------------------------------------
    def state_payload(self) -> str:
        session = self.session
        machine = session.observed_machine_state() if session is not None else None
        return json.dumps(
            {
                "session_ready": bool(session and session.ready),
                "cut_reason": session.cut_reason if session is not None else "",
                "machine_state": machine.value if isinstance(machine, MachineState) else None,
                "global_stop": self.global_stop.state if self.global_stop.enabled else "OFF",
                "observed_at": int(self._clock() * 1000),
            }
        )

    # -- routing ------------------------------------------------------------
    def handle_message(self, topic: str, payload: bytes, *, retained: bool = False) -> list[MqttPublish]:
        if retained or not topic.startswith(TOPIC_PREFIX):
            return []
        suffix = topic[len(TOPIC_PREFIX) :]
        if len(payload) > MAX_PAYLOAD_BYTES:
            return _refusal(suffix, f"payload is larger than {MAX_PAYLOAD_BYTES} bytes")
        refused = self.global_stop.refusal(suffix, payload, moving=MOVING_VERBS)
        if refused is not None:
            return _refusal(suffix, refused)
        try:
            return self._dispatch(suffix, payload)
        except Exception as error:  # noqa: BLE001 - nothing a message does may end the loop
            _LOG.exception("could not handle %s", topic)
            return _refusal(suffix, f"the command could not be handled: {type(error).__name__}")

    def _dispatch(self, suffix: str, payload: bytes) -> list[MqttPublish]:
        result = f"{TOPIC_PREFIX}{suffix}/result"
        if suffix == "cmd/status":
            return [MqttPublish(STATE_TOPIC, self.state_payload(), retain=True)]
        if suffix == "cmd/job":
            return [MqttPublish(result, json.dumps(self._job_answer(payload)), qos=RESULT_QOS)]
        if suffix == "cmd/hold":
            # hold position is a de-escalation and is never gated; the answer says it only names the trigger
            body = {"allowed": True, "executed": False, "action": DroidCoordinator.HOLD_POSITION, "mode": "plan-only", "reason": "hold position requested"}
            return [MqttPublish(result, json.dumps(body), qos=RESULT_QOS)]
        if suffix == "cmd/estop":
            session = self.session
            if session is None:
                body = {"allowed": False, "executed": False, "reason": "no robot session to cut"}
            else:
                session.cut("cut by an operator request over MQTT")
                body = {"allowed": True, "executed": True, "reason": session.cut_reason}
            return [MqttPublish(result, json.dumps(body), qos=RESULT_QOS), MqttPublish(STATE_TOPIC, self.state_payload(), retain=True)]
        return []

    def _job_answer(self, payload: bytes) -> dict[str, object]:
        try:
            raw = json.loads(payload)
        except (ValueError, UnicodeDecodeError) as error:
            return {"allowed": False, "reason": f"malformed job payload: {error}"}
        if not isinstance(raw, dict):
            return {"allowed": False, "reason": "malformed job payload: not an object"}
        session = self.session
        observed = session.observed_machine_state() if session is not None else None
        dispatch = self._coordinator.handle_message(raw, self._cell_state(), observed)
        return {
            "allowed": dispatch.accepted,
            "action": dispatch.action,
            "reason": dispatch.reason,
            "mode": dispatch.mode,
            "parameters": dict(dispatch.parameters),
            "executed": False,
        }


class MessageDispatcher(SharedMessageDispatcher):
    """Takes the messages off the network thread; the stops run on a lane of their own; the announcement of the global stop is read before the retained check."""

    def __init__(self, bridge: DroidMqttBridge, stop_verbs: frozenset[str] = STOP_VERBS, **limits: int) -> None:
        super().__init__(bridge, TOPIC_PREFIX, stop_verbs, **limits)  # type: ignore[arg-type]
        self._droid_bridge = bridge

    def on_message(self, client: object, userdata: object, message: object) -> None:
        guard = self._droid_bridge.global_stop
        if self._droid_bridge.remote_settings and getattr(message, "topic", None) == SETTINGS_TOPIC:
            self._droid_bridge.note_remote_settings(bytes(message.payload), client)  # type: ignore[attr-defined]
            return
        if guard.enabled and getattr(message, "topic", None) == guard.topic:
            self._droid_bridge.note_global_stop(bytes(message.payload))  # type: ignore[attr-defined]
            return
        super().on_message(client, userdata, message)


def _on_connected(bridge: DroidMqttBridge):
    """After every (re)connect: follow the announcement of the global stop (when it is on) and the retained settings of the server (when the host allows them)."""
    if not bridge.global_stop.enabled and not bridge.remote_settings:
        return None

    def on_connected(client: object) -> None:
        if bridge.remote_settings:
            client.subscribe(SETTINGS_TOPIC, qos=1)  # type: ignore[attr-defined]
        if bridge.global_stop.enabled:
            client.subscribe(bridge.global_stop.topic, qos=1)  # type: ignore[attr-defined]

    return on_connected


def run_forever(
    bridge: DroidMqttBridge,
    host: str,
    port: int = 1883,
    client_id: str = "hydra-umc-bridge-droids",
    *,
    max_connect_attempts: int = 5,
    connect_retry_delay_seconds: float = 2.0,
    username: str | None = None,
    password: str | None = None,
    hardening: BridgeHardening | None = None,
) -> None:
    """Connect to the broker and dispatch forever; a thread checks the session in every `tick_interval_s` while it lives."""
    if password is not None and username is None:
        raise ValueError("password was given without a username - MQTT credentials need both")
    hardening = hardening if hardening is not None else hardening_from_environment(GLOBAL_STOP_ENVIRONMENT_NAME)
    dispatcher = MessageDispatcher(bridge, **hardening.dispatcher_kwargs())  # type: ignore[arg-type]
    stop = threading.Event()
    session = bridge.session
    if session is not None:
        interval = session.config.tick_interval_s

        def keep_alive() -> None:
            while not stop.wait(interval):
                if session.ready:
                    session.tick()

        threading.Thread(target=keep_alive, name="droids-keep-alive", daemon=True).start()
    try:
        client = open_bridge_client(
            host,
            port,
            client_id=client_id,
            topic_prefix=TOPIC_PREFIX,
            dispatcher=dispatcher,
            username=username,
            password=password,
            max_connect_attempts=max_connect_attempts,
            connect_retry_delay_seconds=connect_retry_delay_seconds,
            on_connected=_on_connected(bridge),
            **hardening.connect_kwargs(),
        )
        client.loop_forever()  # type: ignore[attr-defined]
    finally:
        stop.set()
        dispatcher.close(wait=False)


__all__ = ["DroidMqttBridge", "MessageDispatcher", "run_forever", "TOPIC_PREFIX"]
