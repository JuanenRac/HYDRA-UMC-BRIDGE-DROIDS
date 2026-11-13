# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - switches announced by the server
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The switches that an administrator sets in Server Admin reach this bridge on one retained topic, signed.

`hydra/bridges/droids/settings` carries `{"schema": 2, "settings": {"globalStop": bool, "cutOnGlobalStop": bool, "confirmationRequired": bool, "returnHomeAlways": bool}, "seq": int, "issued_at_ms": int,
"expires_in_ms": int, "signature": str}`. The signature is the HMAC-SHA256 of the shared signed-command format (`hydra_umc_sdk.signed_commands`) made with the key of the
server for this bridge, which lives in the file named by `HYDRA_UMC_DROIDS_SETTINGS_KEY_FILE`. The bridge listens to the topic only when the host of the bridge allows it
(`HYDRA_UMC_DROIDS_REMOTE_SETTINGS=1`, off by default) AND it has a usable key: without both the topic is not even subscribed and the bridge keeps what its own
environment (`HYDRA_UMC_DROIDS_GLOBAL_STOP`) and its own file (`cut_on_global_stop` in the session configuration) say.

A message is applied only when its signature is valid, it has not expired, it is not from the future and its counter (`seq`) is not older than the last one applied
(a replay of an old message is refused; the same message again changes nothing). An unsigned message, one of the old unsigned format (schema 1), one that is too large,
unreadable or of another schema, or one that carries a value of the wrong type changes nothing; an unknown key is ignored.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Callable, Mapping

from hydra_umc_sdk.signed_commands import CommandSigningError, load_key, verify_command

REMOTE_ENVIRONMENT = "HYDRA_UMC_DROIDS_REMOTE_SETTINGS"
SETTINGS_TOPIC = "hydra/bridges/droids/settings"
MAX_SETTINGS_BYTES = 4096
KEY_ENVIRONMENT = "HYDRA_UMC_DROIDS_SETTINGS_KEY_FILE"
SWITCHES = ("globalStop", "cutOnGlobalStop", "confirmationRequired", "returnHomeAlways")
SIGNED_SCHEMA = 2
MAX_SKEW_MS = 5_000
MAX_EXPIRES_MS = 300_000
_TRUE = {"1", "true", "yes", "on"}
_LOG = logging.getLogger(__name__)


def remote_settings_allowed(environ: Mapping[str, str] | None = None) -> bool:
    """True only when the host of the bridge switched remote settings on."""
    source = os.environ if environ is None else environ
    return source.get(REMOTE_ENVIRONMENT, "").strip().lower() in _TRUE


class SettingsVerifier:
    """Judges the signed settings message: signature, expiry and counter. Without a key it refuses everything (`usable` is False)."""

    def __init__(self, key: bytes | None, *, clock: Callable[[], float] = time.time) -> None:
        self._key = key
        self._clock = clock
        self._last_seq = -1
        self.last_reason = ""

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None, *, clock: Callable[[], float] = time.time) -> "SettingsVerifier":
        """The key comes from the file named by `HYDRA_UMC_DROIDS_SETTINGS_KEY_FILE`; a missing or unusable key gives a verifier that refuses everything."""
        source = os.environ if environ is None else environ
        path = source.get(KEY_ENVIRONMENT, "").strip()
        if not path:
            return cls(None, clock=clock)
        try:
            return cls(load_key(path), clock=clock)
        except CommandSigningError as error:
            _LOG.warning("the key of the signed settings cannot be used, remote settings stay off: %s", error)
            return cls(None, clock=clock)

    @property
    def usable(self) -> bool:
        return self._key is not None

    def accept(self, body: Mapping[str, object]) -> bool:
        """True when the body is signed with the key, current, and not older than the last one accepted."""
        if self._key is None:
            self.last_reason = "no key"
            return False
        verdict = verify_command(SETTINGS_TOPIC, body, self._key, now_ms=int(self._clock() * 1000), max_clock_skew_ms=MAX_SKEW_MS, max_expires_in_ms=MAX_EXPIRES_MS)
        if not verdict.ok:
            self.last_reason = verdict.reason
            return False
        seq = body.get("seq")
        if type(seq) is not int or seq < 0:
            self.last_reason = "the counter is missing"
            return False
        if seq < self._last_seq:
            self.last_reason = "replay: the counter is older than the last one applied"
            return False
        self._last_seq = seq
        self.last_reason = ""
        return True


def parse_remote_settings(payload: bytes, verifier: SettingsVerifier | None = None) -> dict[str, bool] | None:
    """The known switches of a signed message, or None when the message is unsigned, forged, expired, replayed, too large, unreadable or of another schema.
    A wrong type drops the whole message."""
    if verifier is None or len(payload) > MAX_SETTINGS_BYTES:
        return None
    try:
        body = json.loads(payload)
    except (ValueError, RecursionError):
        return None
    if not isinstance(body, dict) or body.get("schema") != SIGNED_SCHEMA or not isinstance(body.get("settings"), dict):
        return None
    if not verifier.accept(body):
        _LOG.warning("a settings message was refused: %s", verifier.last_reason)
        return None
    found: dict[str, bool] = {}
    for key in SWITCHES:
        if key in body["settings"]:
            value = body["settings"][key]
            if not isinstance(value, bool):
                return None
            found[key] = value
    return found
