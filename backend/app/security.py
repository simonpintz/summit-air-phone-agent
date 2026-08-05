"""HMAC verification for Vapi tool-call webhooks.

Vapi signs each webhook request with HMAC-SHA256 of the raw request body,
using the shared secret configured on the tool, and sends it as the
`x-vapi-signature` header. See https://docs.vapi.ai/tools/custom-tools.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from typing import Optional

VAPI_TOOL_SECRET = os.environ.get("VAPI_TOOL_SECRET", "")


def is_valid_signature(raw_body: bytes, signature_header: Optional[str]) -> bool:
    # If no secret is configured, skip verification (useful for local dev).
    # Always require a secret in any deployed environment.
    if not VAPI_TOOL_SECRET:
        return True
    if not signature_header:
        return False

    expected = hmac.new(VAPI_TOOL_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    # Vapi has shipped both a bare hex digest and a "sha256=<hex>" prefixed
    # form across doc revisions - accept either so we're not fragile to that.
    candidate = signature_header
    if candidate.startswith("sha256="):
        candidate = candidate[len("sha256=") :]
    try:
        return hmac.compare_digest(expected, candidate)
    except (TypeError, ValueError):
        return False
