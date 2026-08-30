<!-- =============================================================================
HYDRA-UMC-BRIDGE-DROIDS - Technical bridge guide
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

# HYDRA-UMC-BRIDGE-DROIDS Technical Guide

## Scope and operating model

This bridge maps a validated `BridgeJob` to a **static droid action plan**. The current core has no transport dependency (no Wi-Fi/Bluetooth/cellular socket, no vendor SDK), so it can be verified on Windows, Linux or CI without a real droid. `DroidCoordinator` emits only a named action trigger - `WALK_TO`, `PICK_OBJECT`, `PLACE_OBJECT`, `RETURN_HOME` or `HOLD_POSITION` - plus whether the job's own real parameters satisfy that action's minimum contract, never a joint command, gait pattern or balance instruction.

`PREPARE`/`PROCESS` map to `WALK_TO`, `LOAD` to `PICK_OBJECT`, `UNLOAD` to `PLACE_OBJECT`, `COMPLETE` to `RETURN_HOME`, and `ABORT` to `HOLD_POSITION` - reserved as the one action a droid should always be able to reach regardless of cell state. An unknown SDK phase, or a job missing a required parameter for its own mapped action, is rejected before it is ever forwarded. The result is always `plan-only`, never a live command.

## Compatible platforms

The planned action-trigger boundary is for legged/humanoid droid platforms that retain their own onboard whole-body control authority - typically an embedded compute module (Jetson-class or equivalent) running the platform's own gait/balance stack and exposing a documented command interface over Wi-Fi, Bluetooth or a cellular (4G/5G) link. Compatibility means adapting that platform's own real command interface through a separately deployed transport adapter after one is selected and tested; it does **not** mean this repository drives a droid today.

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
