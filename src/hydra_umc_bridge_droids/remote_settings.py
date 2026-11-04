# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - switches announced by the server
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The switches that an administrator sets in Server Admin reach this bridge on one retained topic.

`hydra/bridges/droids/settings` carries `{"schema": 1, "settings": {"globalStop": bool, "cutOnGlobalStop": bool}}`. The bridge listens to it only when the
host of the bridge allows it: `HYDRA_UMC_DROIDS_REMOTE_SETTINGS=1` (off by default). Without that switch the topic is not even subscribed and the bridge keeps
what its own environment (`HYDRA_UMC_DROIDS_GLOBAL_STOP`) and its own file (`cut_on_global_stop` in the session configuration) say. A message that is too large,
unreadable, of another schema, or that carries a value of the wrong type changes nothing; an unknown key is ignored.
"""

from __future__ import annotations

import json
import os
from typing import Mapping

REMOTE_ENVIRONMENT = "HYDRA_UMC_DROIDS_REMOTE_SETTINGS"
SETTINGS_TOPIC = "hydra/bridges/droids/settings"
MAX_SETTINGS_BYTES = 4096
SWITCHES = ("globalStop", "cutOnGlobalStop")
_TRUE = {"1", "true", "yes", "on"}


def remote_settings_allowed(environ: Mapping[str, str] | None = None) -> bool:
    """True only when the host of the bridge switched remote settings on."""
    source = os.environ if environ is None else environ
    return source.get(REMOTE_ENVIRONMENT, "").strip().lower() in _TRUE


def parse_remote_settings(payload: bytes) -> dict[str, bool] | None:
    """The known switches of a message, or None when the message is too large, unreadable or of another schema. A wrong type drops the whole message."""
    if len(payload) > MAX_SETTINGS_BYTES:
        return None
    try:
        body = json.loads(payload)
    except (ValueError, RecursionError):
        return None
    if not isinstance(body, dict) or body.get("schema") != 1 or not isinstance(body.get("settings"), dict):
        return None
    found: dict[str, bool] = {}
    for key in SWITCHES:
        if key in body["settings"]:
            value = body["settings"][key]
            if not isinstance(value, bool):
                return None
            found[key] = value
    return found
