<!-- =============================================================================
HYDRA-UMC-BRIDGE-DROIDS - Change history
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

# Changelog

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
