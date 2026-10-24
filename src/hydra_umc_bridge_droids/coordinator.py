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

from dataclasses import dataclass, field
import math
from typing import Mapping

from hydra_umc_sdk.bridge_contract import BridgeJob, CellState, JobPhase, MachineState
from hydra_umc_sdk.phase_coordinator import PhaseCoordinator


@dataclass(frozen=True)
class DroidDispatch:
    """The decision for one action, with the validated parameters it was taken on.

    `parameters` holds what the gate actually checked (`x` / `y` as finite
    floats, `object_id` as a stripped string), so a transport sends exactly
    that and not whatever its caller passes alongside.
    """

    accepted: bool
    action: str
    reason: str
    mode: str = "plan-only"
    parameters: Mapping[str, float | str] = field(default_factory=dict)


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

    def __init__(self) -> None:
        # the table of phases, the required parameters, the gate and the standalone requests are the shared coordinator of the SDK;
        # what this class keeps is what is specific to a droid: the meaning of its parameters
        self._phases = PhaseCoordinator(
            self._phase_actions,
            required_parameters=self._REQUIRED_PARAMS,
            validators={
                self.WALK_TO: lambda parameters: self._coordinates(self.WALK_TO, parameters),
                self.PLACE_OBJECT: lambda parameters: self._coordinates(self.PLACE_OBJECT, parameters),
                self.PICK_OBJECT: self._object,
            },
            extra_actions=(self.STAND, self.SIT),
        )

    def action_plan(self) -> DroidActionPlan:
        """Return the static action vocabulary without opening any real transport."""

        return DroidActionPlan("1.1", "plan-only", self._phases.vocabulary())

    @staticmethod
    def _valid_coordinates(parameters: Mapping[str, str]) -> bool:
        """Accept only finite numeric x/y targets at this safety boundary."""

        try:
            return all(math.isfinite(float(parameters[name])) for name in ("x", "y"))
        except (KeyError, TypeError, ValueError):
            return False

    @classmethod
    def _coordinates(cls, action: str, parameters: Mapping[str, str]) -> Mapping[str, object]:
        if not cls._valid_coordinates(parameters):
            raise ValueError(f"{action} requires finite numeric x and y coordinates")
        return {name: float(parameters[name]) for name in ("x", "y")}

    @staticmethod
    def _object(parameters: Mapping[str, str]) -> Mapping[str, object]:
        object_id = str(parameters["object_id"]).strip()
        if not object_id:
            raise ValueError("PICK_OBJECT requires a non-empty object_id")
        return {"object_id": object_id}

    def dispatch(self, job: BridgeJob, cell_state: CellState, observed_machine_state: MachineState | None = None) -> DroidDispatch:
        # `observed_machine_state` is what the droid reported about itself; the claim written in the job is not a reading, so without it the SDK gate refuses every productive job (fail-closed)
        decision = self._phases.decide(job, cell_state, observed_machine_state)
        if decision.action == "none":
            return DroidDispatch(False, "none", "job phase has no mapped droid action trigger")
        return DroidDispatch(decision.accepted, decision.action, decision.reason, parameters=dict(decision.parameters))

    def sit_request(self) -> DroidDispatch:
        """Real, standalone SIT request - deliberately outside the
        JobPhase-driven dispatch() flow above, same reasoning as
        HOLD_POSITION's own ABORT-phase handling: sitting is a real
        de-escalation into a safe, stable, low-energy resting posture
        (the real precondition most legged-robot SDKs require before
        charging - see this coordinator's own STAND/SIT comment), so an
        operator must always be able to request it, not just when the
        cell happens to be READY."""

        decision = self._phases.always_forwarded(self.SIT, "sit requested")
        return DroidDispatch(decision.accepted, self.SIT, decision.reason)

    def stand_request(self, cell_state: CellState, machine_state: MachineState) -> DroidDispatch:
        """Real, standalone STAND request - unlike SIT above, standing up
        is a real productive-readiness transition (the real precondition
        most legged-robot SDKs require before WALK_TO/PICK_OBJECT/etc.
        can run at all), so it goes through the same READY-cell +
        IDLE-machine gate `evaluate_job()` applies to every other
        productive action - accepting `cell_state`/`machine_state`
        directly rather than a full BridgeJob since standing isn't tied
        to any correlated job. The decision is taken by `evaluate_job()` itself
        (on a minimal job that carries only the state), so the rule has one
        source and cannot drift from the SDK's."""

        decision = self._phases.gated_request(self.STAND, cell_state, machine_state)
        return DroidDispatch(decision.accepted, self.STAND, decision.reason)
