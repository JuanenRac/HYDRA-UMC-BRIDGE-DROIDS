<!-- =============================================================================
HYDRA-UMC-BRIDGE-DROIDS - Technical bridge guide
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

# HYDRA-UMC-BRIDGE-DROIDS Technical Guide

## Scope and operating model

This bridge maps a validated `BridgeJob` to a **static droid action plan**. The current core has no transport dependency (no Wi-Fi/Bluetooth/cellular socket, no vendor SDK), so it can be verified on Windows, Linux or CI without a real droid. `DroidCoordinator` emits only a named action trigger - `WALK_TO`, `PICK_OBJECT`, `PLACE_OBJECT`, `RETURN_HOME` or `HOLD_POSITION` - plus whether the job's own real parameters satisfy that action's minimum contract, never a joint command, gait pattern or balance instruction.

`PREPARE`/`PROCESS` map to `WALK_TO`, `LOAD` to `PICK_OBJECT`, `UNLOAD` to `PLACE_OBJECT`, `COMPLETE` to `RETURN_HOME`, and `ABORT` to `HOLD_POSITION` - reserved as the one action a droid should always be able to reach regardless of cell state. An unknown SDK phase, or a job missing a required parameter for its own mapped action, is rejected before it is ever forwarded. `DroidCoordinator.dispatch()` itself is still `plan-only`, never a live command - only `spot_transport.py`'s `SpotDroidControl`, given an already-gated dispatch explicitly, ever reaches the network.

`spot_transport.py` is this bridge's first real transport, targeting Boston Dynamics Spot via bosdyn-client: `sit()`/`stand()`/`walk_to()` build the real, documented `RobotCommandBuilder` command (`synchro_sit_command`/`synchro_stand_command`/`synchro_trajectory_command_in_body_frame`) and send it through `RobotCommandClient.robot_command()`. `stand()` delegates its gate to `DroidCoordinator.stand_request()` rather than re-checking READY/IDLE itself - a single source of truth. `walk_to()`'s `frame_tree_snapshot` is accepted as a caller-supplied opaque value sourced from the robot's own live state (via bosdyn-client's `RobotStateClient`) - this module forwards it, never computes or interprets it. `open_bosdyn_robot_command()` is the one place `bosdyn-client` (optional `[spot]` extra) is imported, lazily.

## Compatible platforms

The action-trigger boundary is for legged/humanoid droid platforms that retain their own onboard whole-body control authority. Boston Dynamics Spot (via bosdyn-client, above) is now a real, implemented transport. A generic transport for a different platform - typically an embedded compute module (Jetson-class or equivalent) running its own gait/balance stack and exposing a documented command interface over Wi-Fi, Bluetooth or a cellular (4G/5G) link - is still future work, introduced only after that platform is selected and tested. Sending a real command still requires a real, reachable Spot and valid credentials - this repository has not been exercised against either yet.

## Scripts and verification

| Script | Purpose | Changes version/CHANGELOG? |
|---|---|---|
| `build-test.bat` / `build-test.sh` | Compile Python and run local tests | No |
| `build.bat` / `build.sh` | Run the same validation, then increment the project version | Yes, after success |

Set `HYDRA_UMC_SDK_ROOT` when the SDK is not a sibling checkout. Use `build-test` during development; it is the only safe default before a real transport adapter exists.

## Adding a new script

Keep a new script in the repository root only when it is an operator entry point. Add the standard copyright header, state whether it mutates version/CHANGELOG, print numbered steps, and end `.bat` scripts with `pause`. Put reusable Python logic under `tools/`, compile it in `tools/build_test.py`, add deterministic tests and document the command in the README and this guide. A script must not open a real transport, discover a droid or send a command implicitly.

## Hardware acceptance gate

Before deploying an adapter: select the real transport (Wi-Fi/BT/4G-5G) and its authentication, document the droid's own command interface and every action trigger's real parameter mapping, bind authenticated droid identity, verify stale/disconnected-state behavior, test `HOLD_POSITION` independently as a real safe fallback, and perform bench validation before any occupied-space test. The droid's own onboard controller remains responsible for balance and motion safety.
