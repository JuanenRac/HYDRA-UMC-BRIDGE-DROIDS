# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - Spot session: e-stop endpoint, lease, power and state reading
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""What a Spot needs before it can be commanded at all, written against small Protocols.

`spot_transport` only builds and sends the commands. A real Spot also needs, in this order:
a software e-stop endpoint that is checked in regularly (the dead-man that cuts the robot when
this process dies), the lease (the right to command the body), motor power, and a reading of the
robot's own state that the gate can use as the observed machine state.

`SpotSession` does that sequence and fails closed at every step: a step that fails stops the
bring-up, leaves the robot unpowered and returns the reason. Every number it uses (timeouts,
battery floor, age of a reading, whether the motors are powered on at the end of the bring-up)
comes from `SpotSessionConfig`, which `load_session_config()` reads from a JSON file; nothing is
fixed in the code. The motors are NOT powered on by default.

The handles are the shape of bosdyn-client's `EstopClient`/`EstopKeepAlive`, `LeaseClient`/
`LeaseKeepAlive`, `Robot.power_on()` and `RobotStateClient.get_robot_state()`; `open_bosdyn_session`
is the one place that imports bosdyn-client. Nothing here has run against a real Spot.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Callable, Mapping, Protocol

from hydra_umc_sdk.bridge_contract import MachineState


class SpotEstopHandle(Protocol):
    """The software e-stop endpoint: registered once, checked in while the bridge lives."""

    def register(self) -> None: ...
    def check_in(self) -> bool: ...
    def cut(self) -> None: ...
    def allow(self) -> None: ...


class SpotLeaseHandle(Protocol):
    def acquire(self) -> None: ...
    def is_alive(self) -> bool: ...
    def release(self) -> None: ...


class SpotPowerHandle(Protocol):
    def power_on(self, timeout_s: float) -> bool: ...
    def power_off(self, timeout_s: float) -> bool: ...


class SpotStateReader(Protocol):
    def get_robot_state(self) -> Mapping[str, object]: ...


@dataclass(frozen=True)
class SpotSessionConfig:
    """Values of the session; the defaults are the conservative ones."""

    estop_timeout_s: float = 9.0
    power_timeout_s: float = 30.0
    min_battery_pct: float = 20.0
    max_state_age_s: float = 5.0
    power_on_after_bring_up: bool = False
    home_waypoint: str = "home"
    cut_on_global_stop: bool = True
    tick_interval_s: float = 2.0

    def problems(self) -> list[str]:
        found: list[str] = []
        for name in ("estop_timeout_s", "power_timeout_s", "max_state_age_s", "tick_interval_s"):
            value = getattr(self, name)
            if not _positive(value):
                found.append(f"{name} must be a finite, positive number")
        if not (_is_number(self.min_battery_pct) and 0 <= self.min_battery_pct <= 100):
            found.append("min_battery_pct must be between 0 and 100")
        if not isinstance(self.power_on_after_bring_up, bool):
            found.append("power_on_after_bring_up must be true or false")
        if not isinstance(self.cut_on_global_stop, bool):
            found.append("cut_on_global_stop must be true or false")
        if not isinstance(self.home_waypoint, str) or not self.home_waypoint.strip():
            found.append("home_waypoint must be a non-empty name")
        return found


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _positive(value: object) -> bool:
    return _is_number(value) and value > 0  # type: ignore[operator]


def load_session_config(path: str | Path | None) -> SpotSessionConfig:
    """Read the session values from a JSON file; no path or a missing file gives the defaults.

    A key that is not a known value, or a value that does not pass `problems()`, is an error:
    a mistyped safety value must not silently fall back to a default.
    """

    if path is None or not Path(path).is_file():
        return SpotSessionConfig()
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("the session configuration must be a JSON object")
    known = {item.name for item in fields(SpotSessionConfig)}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ValueError(f"unknown session configuration keys: {', '.join(unknown)}")
    config = SpotSessionConfig(**raw)
    problems = config.problems()
    if problems:
        raise ValueError("; ".join(problems))
    return config


@dataclass(frozen=True)
class SessionResult:
    ok: bool
    reason: str
    steps: tuple[str, ...] = ()


@dataclass
class SpotSession:
    """Bring-up, check-in and state reading of one Spot, failing closed."""

    estop: SpotEstopHandle
    lease: SpotLeaseHandle
    power: SpotPowerHandle
    state_reader: SpotStateReader
    config: SpotSessionConfig = field(default_factory=SpotSessionConfig)
    clock: Callable[[], float] = time.time
    ready: bool = field(default=False, init=False)
    cut_reason: str = field(default="", init=False)
    _last_state: Mapping[str, object] | None = field(default=None, init=False, repr=False)
    _last_state_at: float = field(default=0.0, init=False, repr=False)

    def bring_up(self) -> SessionResult:
        problems = self.config.problems()
        if problems:
            return SessionResult(False, "invalid session configuration: " + "; ".join(problems))
        steps: list[str] = []
        try:
            self.estop.register()
            steps.append("estop registered")
            self.estop.allow()
            steps.append("estop allows motion")
            self.lease.acquire()
            steps.append("lease acquired")
        except Exception as error:  # a bosdyn error, a lost network: stay unpowered
            self._cut(f"bring-up failed after {steps[-1] if steps else 'nothing'}: {error}")
            return SessionResult(False, self.cut_reason, tuple(steps))
        observed = self.read_state()
        if observed is None:
            self._cut("the state of the robot could not be read")
            return SessionResult(False, self.cut_reason, tuple(steps))
        if self._battery(observed) is not None and self._battery(observed) < self.config.min_battery_pct:  # type: ignore[operator]
            self._cut(f"battery at {self._battery(observed):g} % is under the {self.config.min_battery_pct:g} % floor")
            return SessionResult(False, self.cut_reason, tuple(steps))
        if self.config.power_on_after_bring_up:
            try:
                powered = self.power.power_on(self.config.power_timeout_s)
            except Exception as error:
                self._cut(f"power on failed: {error}")
                return SessionResult(False, self.cut_reason, tuple(steps))
            if not powered:
                self._cut("the motors did not power on in time")
                return SessionResult(False, self.cut_reason, tuple(steps))
            steps.append("motors powered on")
        self.ready = True
        return SessionResult(True, "ready", tuple(steps))

    def tick(self) -> SessionResult:
        """One keep-alive round: check in the e-stop, confirm the lease, refresh the state.

        A check-in that fails, or a lease that is gone, cuts the robot: the bridge does not go on
        commanding a body it may have lost.
        """

        if not self.ready:
            return SessionResult(False, self.cut_reason or "the session is not ready")
        try:
            checked_in = self.estop.check_in()
            alive = self.lease.is_alive()
        except Exception as error:
            self._cut(f"keep-alive failed: {error}")
            return SessionResult(False, self.cut_reason)
        if not checked_in:
            self._cut("the e-stop check-in was refused")
            return SessionResult(False, self.cut_reason)
        if not alive:
            self._cut("the lease was taken by another operator or expired")
            return SessionResult(False, self.cut_reason)
        if self.read_state() is None:
            return SessionResult(True, "alive, but the state could not be refreshed")
        return SessionResult(True, "alive")

    def read_state(self) -> Mapping[str, object] | None:
        try:
            state = self.state_reader.get_robot_state()
        except Exception:
            return None
        if not isinstance(state, Mapping):
            return None
        self._last_state, self._last_state_at = state, self.clock()
        return state

    @staticmethod
    def _battery(state: Mapping[str, object]) -> float | None:
        batteries = state.get("battery_states")
        if not isinstance(batteries, (list, tuple)) or not batteries:
            return None
        levels: list[float] = []
        for entry in batteries:
            if not isinstance(entry, Mapping):
                continue
            level = entry.get("charge_percentage")
            # a real RobotState dictionary wraps the number as {"value": 74.0}
            if isinstance(level, Mapping):
                level = level.get("value")
            if _is_number(level):
                levels.append(float(level))  # type: ignore[arg-type]
        return min(levels) if levels else None

    def observed_machine_state(self) -> MachineState | None:
        """The state the gate may trust, or None when there is no fresh reading (fail-closed).

        ESTOPPED -> STOPPED (an operator must reset it), a behavior fault -> FAULT, a low battery
        -> HOLDING, motors off -> OFFLINE, walking -> RUNNING, standing or sitting with the
        motors on -> IDLE. A lost lease or a cut session is SAFE_STOP.
        """

        if self.cut_reason:
            return MachineState.SAFE_STOP
        state = self._last_state
        if state is None or self.clock() - self._last_state_at > self.config.max_state_age_s:
            return None
        power = state.get("power_state")
        motor = power.get("motor_power_state") if isinstance(power, Mapping) else None
        if motor == "STATE_ESTOPPED":
            return MachineState.STOPPED
        faults = state.get("behavior_fault_state")
        if isinstance(faults, Mapping) and faults.get("faults"):
            return MachineState.FAULT
        if motor != "STATE_ON":
            return MachineState.OFFLINE
        battery = self._battery(state)
        if battery is not None and battery < self.config.min_battery_pct:
            return MachineState.HOLDING
        kinematic = state.get("kinematic_state")
        posture = kinematic.get("posture") if isinstance(kinematic, Mapping) else None
        if posture == "MOVING":
            return MachineState.RUNNING
        return MachineState.IDLE

    def shutdown(self) -> SessionResult:
        """Orderly end: power the motors off, give the lease back. Never raises."""

        steps: list[str] = []
        for name, call in (("motors powered off", lambda: self.power.power_off(self.config.power_timeout_s)), ("lease released", self.lease.release)):
            try:
                call()
                steps.append(name)
            except Exception as error:
                steps.append(f"{name} failed: {error}")
        self.ready = False
        return SessionResult(True, "closed", tuple(steps))

    def cut(self, reason: str) -> None:
        """Cut the robot from outside the session (a global stop, a zone violation): the e-stop endpoint stops being checked in and the session is no longer ready."""
        if not self.cut_reason:
            self._cut(reason)

    def _cut(self, reason: str) -> None:
        self.cut_reason = reason
        self.ready = False
        try:
            self.estop.cut()
        except Exception:
            pass  # the e-stop endpoint stops being checked in; the robot's own timeout cuts it


def open_bosdyn_session(hostname: str, username: str, password: str, config: SpotSessionConfig | None = None) -> SpotSession:
    """Authenticate against a real Spot and return its session (bosdyn-client is imported here only)."""

    try:
        import bosdyn.client  # type: ignore[import-untyped]
        import bosdyn.client.estop  # type: ignore[import-untyped]
        import bosdyn.client.lease  # type: ignore[import-untyped]
        from bosdyn.client.robot_state import RobotStateClient  # type: ignore[import-untyped]
    except ImportError as error:
        raise RuntimeError("bosdyn-client is not installed - install it to open a session with a real Spot") from error
    from google.protobuf import json_format  # type: ignore[import-untyped]

    settings = config or SpotSessionConfig()
    sdk = bosdyn.client.create_standard_sdk("hydra-umc-bridge-droids")
    robot = sdk.create_robot(hostname)
    robot.authenticate(username, password)
    robot.time_sync.wait_for_sync()
    estop_client = robot.ensure_client(bosdyn.client.estop.EstopClient.default_service_name)
    lease_client = robot.ensure_client(bosdyn.client.lease.LeaseClient.default_service_name)
    state_client = robot.ensure_client(RobotStateClient.default_service_name)

    class _Estop:
        keep_alive = None

        def register(self) -> None:
            endpoint = bosdyn.client.estop.EstopEndpoint(estop_client, "hydra-umc-bridge-droids", settings.estop_timeout_s)
            endpoint.force_simple_setup()
            self.keep_alive = bosdyn.client.estop.EstopKeepAlive(endpoint)

        def check_in(self) -> bool:
            return self.keep_alive is not None and self.keep_alive.status_queue.empty()

        def cut(self) -> None:
            if self.keep_alive is not None:
                self.keep_alive.stop()

        def allow(self) -> None:
            if self.keep_alive is not None:
                self.keep_alive.allow()

    class _Lease:
        keep_alive = None

        def acquire(self) -> None:
            self.keep_alive = bosdyn.client.lease.LeaseKeepAlive(lease_client, must_acquire=True, return_at_exit=True)

        def is_alive(self) -> bool:
            return self.keep_alive is not None and self.keep_alive.is_alive()

        def release(self) -> None:
            if self.keep_alive is not None:
                self.keep_alive.shutdown()

    class _Power:
        def power_on(self, timeout_s: float) -> bool:
            robot.power_on(timeout_sec=timeout_s)
            return bool(robot.is_powered_on())

        def power_off(self, timeout_s: float) -> bool:
            robot.power_off(cut_immediately=False, timeout_sec=timeout_s)
            return not robot.is_powered_on()

    class _State:
        def get_robot_state(self) -> Mapping[str, object]:
            return json_format.MessageToDict(state_client.get_robot_state(), preserving_proto_field_name=True)

    return SpotSession(_Estop(), _Lease(), _Power(), _State(), settings)
