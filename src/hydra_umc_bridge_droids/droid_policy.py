# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - Policy of the job entry: signed human confirmation for the actions that move the droid
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""What the MQTT job entry asks BEFORE the shared gate of the SDK sees a job that moves the droid.

A job that walks the droid, picks or places an object must carry `operator_confirmation`: a short token signed by the SERVER for that action and that `job_id`,
valid once (see `human_confirmation.py`). It is on by default (`policy.confirmation_required` in `config/bridge.json`). It only adds refusals: it never relaxes the gate of
the SDK. Holding position and returning home are de-escalations and never need it. The token is used up only when the gate accepts the job, so a job refused for another
reason does not burn it, and a refused job leaves its idempotency key free.

Simulator evidence only; nothing here has run against a real server or a real droid.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .human_confirmation import Confirmation, ConfirmationError, ConfirmationVerifier

CONFIRMATION_FIELD = "operator_confirmation"
CONFIRMED_ACTIONS = frozenset({"WALK_TO", "PICK_OBJECT", "PLACE_OBJECT"})


@dataclass(frozen=True)
class PolicyVerdict:
    accepted: bool
    reason: str
    confirmation: Confirmation | None = None


class DroidPolicy:
    def __init__(self, confirmation_required: bool = True, verifier: ConfirmationVerifier | None = None, actions: frozenset[str] = CONFIRMED_ACTIONS) -> None:
        self.confirmation_required = confirmation_required  # remote settings may switch it ON, never off
        self.verifier = verifier
        self.actions = frozenset(actions)

    def review(self, payload: Mapping[str, object], action: str | None) -> PolicyVerdict:
        if not self.confirmation_required or action not in self.actions:
            return PolicyVerdict(True, "no policy applies")
        if self.verifier is None:
            return PolicyVerdict(False, "no confirmation key is configured (policy.confirmation_key_file in config/bridge.json): the job is refused")
        job_id = payload.get("job_id")
        try:
            confirmation = self.verifier.verify(payload.get(CONFIRMATION_FIELD), action=action, job_id=job_id if isinstance(job_id, str) else "")
        except ConfirmationError as error:
            return PolicyVerdict(False, str(error))
        return PolicyVerdict(True, "the confirmation is valid", confirmation)

    def use(self, verdict: PolicyVerdict) -> str | None:
        """Called when the gate accepted the job: uses the confirmation up. A reason comes back when it was used meanwhile (the job must then be refused)."""
        if verdict.confirmation is not None and self.verifier is not None and not self.verifier.consume(verdict.confirmation):
            return "this confirmation was already used"
        return None
