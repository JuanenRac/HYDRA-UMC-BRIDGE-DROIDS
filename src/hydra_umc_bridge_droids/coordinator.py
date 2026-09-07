# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - Droid action-trigger coordinator
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Map a correlated cell job onto named droid action triggers, never raw motion.

This module deliberately never computes gait, balance or joint trajectories -
it only validates and forwards a small, named vocabulary of whole-body action
triggers (WALK_TO, PICK_OBJECT, ...) plus their real required parameters. The
droid's own onboard controller (Jetson or equivalent) keeps full authority
over how it actually walks there - the same reasoning HYDRA-UMC-BRIDGE-ROS2's
own coordinator.py already documents for topics/services/actions, applied
here to a transport-agnostic (Wi-Fi/BT/4G-5G) action-trigger link instead.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

from hydra_umc_sdk.bridge_contract import BridgeJob, CellState, JobPhase, MachineState, evaluate_job


@dataclass(frozen=True)
class DroidDispatch:
    accepted: bool
    action: str
    reason: str
    mode: str = "plan-only"


@dataclass(frozen=True)
class DroidActionPlan:
    """Static evidence of the real action vocabulary, not a discovered device."""

    schema_version: str
    mode: str
    actions: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "mode": self.mode, "actions": list(self.actions)}


class DroidCoordinator:
    """Gate jobs before a future transport adapter reaches a real droid."""

    WALK_TO = "WALK_TO"
    PICK_OBJECT = "PICK_OBJECT"
    PLACE_OBJECT = "PLACE_OBJECT"
    RETURN_HOME = "RETURN_HOME"
    HOLD_POSITION = "HOLD_POSITION"
    # Real, near-universal legged-robot posture commands this coordinator
    # never modeled at all before - checked against Boston Dynamics'
    # real, public Spot SDK (github.com/boston-dynamics/spot-sdk
    # protos/bosdyn/api/basic_command.proto), whose own foundational
    # mobility commands are stand/sit/selfright/safe_power_off, not just
    # walk/manipulate. STAND and SIT are the two most basic real posture
    # states across legged-robot SDKs generally (a droid that can't be
    # told to sit before charging, or stand up before a job, is missing
    # a real operational primitive, not an edge case). Neither computes
    # balance/gait itself (same "onboard controller keeps authority"
    # scope as every other action here) - each is just the named
    # trigger, same as WALK_TO/PICK_OBJECT/etc.
    STAND = "STAND"
    SIT = "SIT"

    # Real, minimal per-action parameter contract - not full IK/planning
    # input, just the named string parameters this coordination boundary can
    # actually validate before forwarding an action trigger downstream.
    _REQUIRED_PARAMS: Mapping[str, tuple[str, ...]] = {
        WALK_TO: ("x", "y"),
        PICK_OBJECT: ("object_id",),
        PLACE_OBJECT: ("x", "y"),
        RETURN_HOME: (),
        HOLD_POSITION: (),
        STAND: (),
        SIT: (),
    }

    # One real action per job phase - PREPARE/PROCESS both walk (to a
    # staging point, then to the drop-off), LOAD/UNLOAD pick/place, COMPLETE
    # returns home, and ABORT freezes in place rather than continuing to
    # move - never routed through evaluate_job's own IDLE/READY requirement
    # (see that function's own "abort requests are always forwarded"
    # comment), matching every sibling bridge's own ABORT handling.
    _phase_actions = {
        JobPhase.PREPARE: WALK_TO,
        JobPhase.LOAD: PICK_OBJECT,
        JobPhase.PROCESS: WALK_TO,
        JobPhase.UNLOAD: PLACE_OBJECT,
        JobPhase.COMPLETE: RETURN_HOME,
        JobPhase.ABORT: HOLD_POSITION,
    }

    def action_plan(self) -> DroidActionPlan:
        """Return the static action vocabulary without opening any real transport."""

        return DroidActionPlan("1.1", "plan-only", tuple(self._REQUIRED_PARAMS))

    @staticmethod
    def _valid_coordinates(parameters: Mapping[str, str]) -> bool:
        """Accept only finite numeric x/y targets at this safety boundary."""

        try:
            return all(math.isfinite(float(parameters[name])) for name in ("x", "y"))
        except (KeyError, TypeError, ValueError):
            return False

    def dispatch(self, job: BridgeJob, cell_state: CellState) -> DroidDispatch:
        action = self._phase_actions.get(job.phase)
        if action is None:
            return DroidDispatch(False, "none", "job phase has no mapped droid action trigger")
        required = self._REQUIRED_PARAMS[action]
        missing = [name for name in required if name not in job.parameters]
        if missing:
            return DroidDispatch(False, action, f"missing required parameter(s) for {action}: {', '.join(missing)}")
        if action in (self.WALK_TO, self.PLACE_OBJECT) and not self._valid_coordinates(job.parameters):
            return DroidDispatch(False, action, f"{action} requires finite numeric x and y coordinates")
        if action == self.PICK_OBJECT and not str(job.parameters["object_id"]).strip():
            return DroidDispatch(False, action, "PICK_OBJECT requires a non-empty object_id")
        decision = evaluate_job(job, cell_state)
        return DroidDispatch(decision.allowed, action, decision.reason)

    def sit_request(self) -> DroidDispatch:
        """Real, standalone SIT request - deliberately outside the
        JobPhase-driven dispatch() flow above, same reasoning as
        HOLD_POSITION's own ABORT-phase handling: sitting is a real
        de-escalation into a safe, stable, low-energy resting posture
        (the real precondition most legged-robot SDKs require before
        charging - see this coordinator's own STAND/SIT comment), so an
        operator must always be able to request it, not just when the
        cell happens to be READY."""

        return DroidDispatch(True, self.SIT, "sit requested - always forwarded regardless of cell/machine state")

    def stand_request(self, cell_state: CellState, machine_state: MachineState) -> DroidDispatch:
        """Real, standalone STAND request - unlike SIT above, standing up
        is a real productive-readiness transition (the real precondition
        most legged-robot SDKs require before WALK_TO/PICK_OBJECT/etc.
        can run at all), so it goes through the same READY-cell +
        IDLE-machine gate `evaluate_job()` applies to every other
        productive action - accepting `cell_state`/`machine_state`
        directly rather than a full BridgeJob since standing isn't tied
        to any correlated job."""

        if cell_state is not CellState.READY:
            return DroidDispatch(False, self.STAND, f"cell is {cell_state.value}, not READY")
        if machine_state is not MachineState.IDLE:
            return DroidDispatch(False, self.STAND, f"external machine is {machine_state.value}, not IDLE")
        return DroidDispatch(True, self.STAND, "cell and external machine are ready")
