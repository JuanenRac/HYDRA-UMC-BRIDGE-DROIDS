<!-- =============================================================================
HYDRA-UMC-BRIDGE-DROIDS - Change history
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

# Changelog

## [0.0.3] - Real STAND/SIT posture commands

- **`coordinator.py`** - added `STAND`/`SIT`, real posture primitives this
  coordinator never modeled at all before. Researched against Boston
  Dynamics' real, public
  [Spot SDK `basic_command.proto`](https://github.com/boston-dynamics/spot-sdk/blob/master/protos/bosdyn/api/basic_command.proto):
  its own foundational mobility commands are `stand`/`sit`/`selfright`/
  `safe_power_off`, not just walk/manipulate - a real, near-universal
  legged-robot vocabulary this bridge's own `WALK_TO`/`PICK_OBJECT`-only
  set was missing entirely.
- `sit_request()`/`stand_request()` (new) expose them as standalone
  requests, deliberately outside the `JobPhase`-driven `dispatch()` flow
  (no phase naturally means "stand up" or "sit down"). `sit_request()`
  is always accepted - a real de-escalation into a safe, stable resting
  posture, same reasoning as `HOLD_POSITION`. `stand_request()` requires
  a `READY` cell and `IDLE` machine - a real productive-readiness
  transition, gated the same way every other productive action here is.
- `action_plan()`'s static schema bumped `1.0` -> `1.1` (now includes
  `STAND`/`SIT`).
- 3 new regression tests - 13/13 tests (3 subtests) passing.

## [0.0.2] - Finite-coordinate and non-empty-identifier gate

- Required finite numeric coordinates for `WALK_TO` and `PLACE_OBJECT`, and a
  non-empty identifier for `PICK_OBJECT`, before any future droid transport.
- 10/10 tests passing.

## [0.0.1]

- Added a dependency-free droid coordination core (`DroidCoordinator`):
  a real, named action-trigger vocabulary (`WALK_TO`/`PICK_OBJECT`/
  `PLACE_OBJECT`/`RETURN_HOME`/`HOLD_POSITION`), each with its own real
  required-parameter contract validated before a job ever reaches the
  shared `HYDRA-UMC-SDK` safety gate.
- Added non-mutating build-test scripts and CI SDK checkout, matching
  the rest of the External Automation / Mobile Bridges family.
- Standardized README in all 7 ecosystem languages (English, Spanish,
  French, Italian, German, Simplified Chinese, Japanese), project banner
  and manifest to match the ecosystem's established-project structure.
- No real Wi-Fi/BT/4G-5G transport adapter or physical droid validated
  yet - this is a plan-only coordination boundary.
