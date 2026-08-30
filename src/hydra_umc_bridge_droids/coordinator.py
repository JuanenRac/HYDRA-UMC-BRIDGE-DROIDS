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
from typing import Mapping

from hydra_umc_sdk.bridge_contract import BridgeJob, CellState, JobPhase, evaluate_job


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

    # Real, minimal per-action parameter contract - not full IK/planning
    # input, just the named string parameters this coordination boundary can
    # actually validate before forwarding an action trigger downstream.
    _REQUIRED_PARAMS: Mapping[str, tuple[str, ...]] = {
        WALK_TO: ("x", "y"),
        PICK_OBJECT: ("object_id",),
        PLACE_OBJECT: ("x", "y"),
        RETURN_HOME: (),
        HOLD_POSITION: (),
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

        return DroidActionPlan("1.0", "plan-only", tuple(self._REQUIRED_PARAMS))

    def dispatch(self, job: BridgeJob, cell_state: CellState) -> DroidDispatch:
        action = self._phase_actions.get(job.phase)
        if action is None:
            return DroidDispatch(False, "none", "job phase has no mapped droid action trigger")
        required = self._REQUIRED_PARAMS[action]
        missing = [name for name in required if name not in job.parameters]
        if missing:
            return DroidDispatch(False, action, f"missing required parameter(s) for {action}: {', '.join(missing)}")
        decision = evaluate_job(job, cell_state)
        return DroidDispatch(decision.allowed, action, decision.reason)
