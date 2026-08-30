<!-- =============================================================================
HYDRA-UMC-BRIDGE-DROIDS - Contribution guide
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

# Contributing

Keep this bridge a coordination layer: it sends only destination points and
named action triggers (e.g. `WALK_TO`, `PICK_OBJECT`) - whole-body gait,
balance and joint-level control remain the droid's own onboard authority
(Jetson or equivalent), never this repository.

Before opening a change, run `build-test.bat` on Windows or `bash build-test.sh`
on Linux. Add a focused test for each state mapping or admission rule changed.
Hardware-dependent behavior must state its tested platform, transport and
safe failure mode; unverified hardware support must not be presented as ready.
