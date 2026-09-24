# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - Public package interface
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================

"""Fail-safe, high-level droid coordination planning for HYDRA-UMC."""

from hydra_umc_sdk.bridge_contract import BridgeJob, CellState, JobPhase, MachineState

from .coordinator import DroidActionPlan, DroidCoordinator, DroidDispatch
from .platform_profiles import MOBILE_MANIPULATOR, MOBILE_ONLY, PROFILES, PlatformProfile, SimulatedDroid, check_against_profile
from .spot_transport import SpotDroidControl, SpotSendResult, open_bosdyn_robot_command

__all__ = [
    "BridgeJob",
    "CellState",
    "JobPhase",
    "MachineState",
    "DroidActionPlan",
    "DroidCoordinator",
    "DroidDispatch",
    "PlatformProfile",
    "SimulatedDroid",
    "MOBILE_ONLY",
    "MOBILE_MANIPULATOR",
    "PROFILES",
    "check_against_profile",
    "SpotDroidControl",
    "SpotSendResult",
    "open_bosdyn_robot_command",
]
