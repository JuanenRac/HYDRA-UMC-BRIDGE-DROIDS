<!-- =============================================================================
HYDRA-UMC-BRIDGE-DROIDS - Change history
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

# Changelog

## [Unreleased] - Maturity raised to established

- **`spot_transport.py`'s `_send()` now catches real bosdyn-client
  failures, not just `OSError`** - found in an ecosystem-wide
  software-improvements audit: a real bosdyn-client failure (expired
  auth token, RPC timeout, a real robot fault) raises from bosdyn's own
  exception hierarchy (`bosdyn.client.exceptions.Error`), not `OSError`
  - it used to propagate uncaught instead of degrading to a clean
  `SpotSendResult(False, ...)` like this bridge's other transports
  already do. The real exception class is imported lazily (same
  reasoning as `open_bosdyn_robot_command()`) and narrowly matched - a
  genuine bug in this module's own code still surfaces as an unhandled
  exception rather than being silently downgraded. New regression tests
  prove both paths: a real bosdyn error degrading cleanly (a fake
  `bosdyn.client.exceptions` module is injected into `sys.modules` to
  exercise the real import-and-isinstance-check code without needing the
  real SDK installed) and an unrelated bug still propagating.
- **`hydra-umc.project.json`** - `maturity` raised from `functional` to
  `established`, matching the real substance already shipped in 0.0.4
  (real, gated coordination logic plus a real bosdyn-client Spot command
  sender, lazily imported, same rigor and scope as sibling bridges
  already marked `established` - e.g. HYDRA-UMC-BRIDGE-CNC). Metadata-only,
  no code change, no version bump.

## [0.0.6] - A bosdyn-client-shaped Spot emulator, not a record-only fake sink

Until now the only doubles here were `FakeBuilder` (opaque sentinels) and
`FakeSink` (records one call, or raises). A real Spot's
`RobotCommandClient.robot_command()` accepts a real `RobotCommand`
protobuf whose `synchronized_command.mobility_command` carries exactly
one of a `stand_request` / `sit_request` / `se2_trajectory_request`;
returns a `RobotCommandResponse` with an integer `command_id` and a
`status` from the real `RobotCommandResponse.Status` enum (`STATUS_OK`,
`STATUS_NOT_POWERED_ON`, `STATUS_EXPIRED`, `STATUS_TOO_DISTANT`,
`STATUS_BEHAVIOR_FAULT`, ...), NOT an exception for a command the robot
simply cannot execute - only for a real RPC / lease failure; and moves
the robot through a real posture/motion state machine a caller polls with
`robot_command_feedback(command_id)`.

New `tests/spot_emulator.py`: `SpotCommandBuilderEmulator` builds
real-proto-shaped command objects; `SpotRobotEmulator` (the sink)
executes them against that state machine (POWERED_OFF / SITTING /
STANDING / MOVING), rejecting a trajectory from a sit with
`STATUS_BEHAVIOR_FAULT`, one past the ~50 m body-frame limit with
`STATUS_TOO_DISTANT`, one with an `end_time_secs` in the past with
`STATUS_EXPIRED`, and every motion command while E-stopped with
`STATUS_NOT_POWERED_ON`. `engage_estop()` / `set_lease_held()` /
`power_off()` / `raise_behavior_fault()` drive the physical side; a lease
lost mid-RPC is raised as `OSError` so `SpotDroidControl._send()`
degrades it cleanly. New `tests/test_spot_emulator.py` runs this
bridge's real `SpotDroidControl` end to end against it (9 tests): the
full stand -> walk -> arrive (via feedback) -> sit lifecycle over real
proto commands, and each real refusal path. 31 tests total.

## [0.0.5] - V07-014: the SDK's own real phase-construction rejection reached this bridge's test suite

A second independent revalidation audit found this bridge's own
`test_unknown_sdk_phase_fails_closed_instead_of_guessing_an_action` still
constructed a `BridgeJob` directly with a raw `"SOME_FUTURE_PHASE"`
string - HYDRA-UMC-SDK's own real fix (REV-008) now rejects that AT
CONSTRUCTION TIME, so the test never even reached the coordinator's own
assertion. Split in two, same as HYDRA-UMC-BRIDGE-UAV's own
already-updated test: a new
`test_constructing_a_bridge_job_with_an_unknown_phase_is_refused_by_the_sdk_itself`
proves the SDK's own real rejection, and the original test now uses a
minimal explicit double (`SimpleNamespace(phase=...)`) to keep proving
`DroidCoordinator.dispatch()`'s own defensive `_phase_actions.get(...)`
fallback still fails closed - real defense-in-depth, not weakened to let
the old construction succeed again.

## [0.0.4] - Real bosdyn-client Spot command transport (pre-real: connected, not simulated)

- **`spot_transport.py`** (new) - this bridge's first real transport:
  `SpotDroidControl` builds and sends real Boston Dynamics bosdyn-client
  commands for an already-gated dispatch, using the real, documented API
  ([dev.bostondynamics.com/python/bosdyn-client](https://dev.bostondynamics.com/python/bosdyn-client/src/bosdyn/client/robot_command)):
  `sit()` -> `RobotCommandBuilder.synchro_sit_command()` (always allowed,
  same reasoning as `DroidCoordinator.sit_request()`); `stand()` ->
  `RobotCommandBuilder.synchro_stand_command()`, gated through
  `DroidCoordinator.stand_request()`'s own READY+IDLE check rather than
  re-implementing it; `walk_to()` ->
  `RobotCommandBuilder.synchro_trajectory_command_in_body_frame(...)`,
  gated on an already-accepted `DroidDispatch`. All three send through
  `RobotCommandClient.robot_command()`. Both the command builder and the
  command sink are written against small Protocols matching bosdyn-client's
  own real method signatures, so the gating/composition logic is
  unit-testable with plain fakes - no real Spot, network, or bosdyn-client
  install required. `open_bosdyn_robot_command()` is the one place
  `bosdyn-client` (new optional `[spot]` extra) is imported, lazily,
  following its own documented bring-up sequence (create SDK, create robot,
  authenticate, wait for time sync, get the command client), degrading to a
  clear `RuntimeError` instead of a bare `ImportError` when it isn't
  installed.
- 6 new regression tests against fake builder/sink objects - 19/19 tests
  passing.

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
