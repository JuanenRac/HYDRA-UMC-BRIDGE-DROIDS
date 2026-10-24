# Changelog

All notable changes to this project are documented here.

## [Unreleased]

- **The phase table, the required parameters and the gate are the shared phase coordinator of the SDK** (`hydra_umc_sdk.phase_coordinator`), the same one the UAV and AMR bridges use. The actions, the order of the vocabulary and the answers are unchanged.
- Building no longer changes the version; raising it is the explicit `bump` command (`python tools/hydra_project_tool.py bump`). The build scripts only report the version they built, and CI fails if a build script runs a bump.
- The banner follows the animated style of the ecosystem banners, with the name, the kind and the technologies of the project.
- Added `tools/hydra_project_tool.py`: the same `validate`, `test`, `version`, `status` and `bump` commands in every repository. The checks run with `HYDRA_UMC_CI=1` and fail if the version changes; only `bump` changes it.
- The SDK is now fetched at a release tag instead of the main branch, so a change of the SDK cannot break this repository by itself.
- The SDK is pinned to 0.3.6, whose gate refuses a productive job when the bridge did not read the state of its machine. `DroidCoordinator.dispatch()` must be given the state the droid reported; without it the job is refused, and the claim written in the job message is no longer trusted. The tests now pass the observed state explicitly and check the refusal when there is none.

## [0.1.2]

- Successful incremental build: synchronized package metadata and `hydra-umc.project.json`.
- The licence is written as GPL-3.0-or-later in every header and in the package metadata.

## [0.1.1] - Maturity lowered to functional
- Maturity is functional: the code, tests and documentation are in place, but nothing here has been verified on real hardware yet, so the manifest no longer claims the established level.

## [0.1.0] - A stop that reaches the robot, goals that are the ones validated and a walk that expires

- **`HOLD_POSITION` has a transport.** `SpotDroidControl.hold_position()` sends bosdyn's `stop_command()` and is never gated. Before, `ABORT` mapped to `HOLD_POSITION` and the dispatch was accepted, but no method sent it, so a walking robot kept going to its goal.
- **`walk_to()` sends what the gate validated.** A `DroidDispatch` now carries the parameters it validated (`x` / `y` as finite floats, `object_id`) and `walk_to()` reads the goal from there instead of taking `goal_x` / `goal_y` next to it: the signature changes to `walk_to(builder, sink, dispatch, *, frame_tree_snapshot, command_timeout_s, goal_heading=0.0, max_distance_m=None)`. It refuses a dispatch that is not a `WALK_TO` (an accepted `PICK_OBJECT` used to be enough to walk), a goal or heading that is not finite, and a goal beyond `max_distance_m` (`PlatformProfile.max_walk_distance_m` is the profile's limit, none by default).
- **The walk expires.** `command_timeout_s` is required and becomes the command's `end_time_secs`, so the robot drops a walk that outlived this process instead of continuing to the goal unsupervised.
- **`sit()` stops the robot first** (`stop_first=True`, on by default) instead of sitting it down mid-stride, and does not sit a robot it could not stop. It still does not know where the robot stands.
- **`stand_request()`** takes its decision from `evaluate_job()` itself instead of repeating the rule, so it cannot drift from the SDK.
- **Refused commands are not "sent".** The real client returns a command id and raises for a command the robot cannot run; the test emulator now does the same (its refusals used to be a status in a returned object, and a test asserted `sent` for a command the robot had refused), and a response object whose `status` is not OK is not reported as sent.
- **Documentation.** The README and the guide no longer say the transport is missing, mention Bluetooth, or draw a path to the server that does not exist; they say what is missing before a real Spot can be commanded; `LICENSE` carries the full GPL-3.0-or-later text and the test counts are corrected.
- Not run against a real Spot or the vendor's simulator. The lease, the software E-Stop endpoint with its keep-alive and the motor power-on are not implemented, so this cannot command a real Spot yet; `RETURN_HOME`, `PICK_OBJECT` and `PLACE_OBJECT` have no transport.
- 14 new tests (57 in total); an unused import in the CI validator removed.

## [0.0.9] - The gate can use the machine state the droid reports

- **Observed machine state.** `DroidCoordinator.dispatch()` takes the state the droid reported as an optional argument; when it is given it replaces the `machine_state` a requester wrote in the job (a message anybody on the broker may publish) in the shared gate. Without it the claim is still used. `stand_request()` already took the machine state explicitly.
- Four new tests (tests/test_observed_state.py).

## [0.0.8] - Platform capability profiles and a simulated droid

- **Platform capability profiles and a simulated droid** (`platform_profiles.py`):
  `MOBILE_ONLY` and `MOBILE_MANIPULATOR` state the minimum a platform must
  support for an action trigger to be forwarded to it. `check_against_profile()`
  refuses an action outside the profile (for example pick/place on a
  mobile-only platform) instead of sending it to hardware without that
  capability; `HOLD_POSITION` is never blocked. `SimulatedDroid` records
  what a profile accepts with pure bookkeeping - it imports no transport
  and cannot produce real motion. Eight new tests (39 in total).

## [0.0.7] - spot_transport.py now catches real bosdyn-client failures, not just OSError

- **`spot_transport.py`'s `_send()` now catches real bosdyn-client
  failures, not just `OSError`** - a real bosdyn-client failure (expired
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

## [0.0.5] - The SDK's own real phase-construction rejection reached this bridge's test suite

A second, closer review found this bridge's own
`test_unknown_sdk_phase_fails_closed_instead_of_guessing_an_action` still
constructed a `BridgeJob` directly with a raw `"SOME_FUTURE_PHASE"`
string - HYDRA-UMC-SDK's own real fix now rejects that AT
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
