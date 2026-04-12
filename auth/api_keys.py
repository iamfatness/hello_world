"""API key authentication for machine-to-machine endpoints.

The `/ivr/*`, `/webhook/*`, and `/api/*` routes are called by machines
(Cisco IP phones, CUCM webhook posts, external API clients) that cannot
complete an interactive OAuth2 login flow. This module provides a
lightweight token-based scheme for those callers.

Design:
- Keys are generated as `ckuk_<32 random hex chars>` (42 chars total).
- Only a SHA-256 hash of the key is stored; the plaintext is shown to
  the admin exactly once at creation time.
- A short "key_prefix" (the first 8 chars) is stored unhashed so admins
  can identify keys in the management UI without seeing the secret.
- Callers supply the key via either the `X-API-Key` header or an
  `api_key` query-string parameter (query string is convenient for
  Cisco Phone Service URLs that can't set headers).
- The `machine_auth_required` hook accepts EITHER a valid SSO session
  (so authenticated admins can still browse/test endpoints) OR a valid
  API key.
- When `API_AUTH_ENABLED=False` (the default for backwards compatibility)
  requests pass through unauthenticated.
"""

import datetime
import hashlib
import logging
import secrets

from flask import current_app, request, session, jsonify

logger = logging.getLogger(__name__)

KEY_PREFIX_LEN = 8
KEY_TOKEN_PREFIX = "ckuk_"


def generate_api_key():
    """Generate a new random API key.

    Returns:
        The plaintext key string (only returned once, never stored).
    """
    return KEY_TOKEN_PREFIX + secrets.token_hex(16)


def hash_key(plaintext):
    """Compute the SHA-256 hex digest of a plaintext API key."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def extract_key_prefix(plaintext):
    """Return the short public prefix used to identify a key in the UI."""
    return plaintext[:KEY_PREFIX_LEN]


def create_api_key(db_session, name, created_by=""):
    """Create and persist a new API key.

    Args:
        db_session: SQLAlchemy session.
        name: Human-readable label (e.g., "CUCM Webhook", "IVR Phone").
        created_by: Email of the admin creating the key.

    Returns:
        Tuple (plaintext_key, ApiKey row). The plaintext is only
        available in this response - it cannot be retrieved later.
    """
    from models.database import ApiKey

    plaintext = generate_api_key()
    key = ApiKey(
        name=name,
        key_prefix=extract_key_prefix(plaintext),
        key_hash=hash_key(plaintext),
        created_by=created_by,
        revoked=False,
    )
    db_session.add(key)
    db_session.commit()
    return plaintext, key


def verify_api_key(db_session, plaintext):
    """Check whether a plaintext key matches an active stored key.

    Also updates last_used_at on success.

    Returns:
        The ApiKey row if valid, else None.
    """
    from models.database import ApiKey

    if not plaintext:
        return None

    key_hash = hash_key(plaintext)
    key = (
        db_session.query(ApiKey)
        .filter(ApiKey.key_hash == key_hash, ApiKey.revoked.is_(False))
        .first()
    )
    if not key:
        return None

    key.last_used_at = datetime.datetime.utcnow()
    db_session.commit()
    return key


def _extract_request_key():
    """Pull an API key from the request, trying header then query string."""
    header_key = request.headers.get("X-API-Key", "").strip()
    if header_key:
        return header_key

    # Some Cisco IP phone services and CUCM HTTP URLs can only pass
    # query parameters - accept api_key there as well.
    query_key = request.args.get("api_key", "").strip()
    if query_key:
        return query_key

    # Some older Cisco services send form-encoded POSTs.
    form_key = request.form.get("api_key", "").strip() if request.form else ""
    return form_key


def machine_auth_required():
    """Flask before_request hook: require API key OR SSO session.

    Returns None (allow) or a Response (deny) as required by before_request.
    """
    # Master switch - off by default for backwards compatibility.
    if not current_app.config.get("API_AUTH_ENABLED"):
        return None

    # If an admin is already signed in via SSO, let them through so
    # they can hit these endpoints from the browser for testing.
    if session.get("user"):
        return None

    plaintext = _extract_request_key()
    if not plaintext:
        logger.warning(
            "Unauthenticated machine request rejected: %s %s",
            request.method,
            request.path,
        )
        return (
            jsonify({"error": "Authentication required", "hint": "Provide X-API-Key header or api_key query parameter"}),
            401,
        )

    db_session = current_app.config["DB_SESSION_FACTORY"]()
    try:
        key = verify_api_key(db_session, plaintext)
        if not key:
            logger.warning(
                "Invalid API key on %s %s", request.method, request.path
            )
            return jsonify({"error": "Invalid or revoked API key"}), 401
    finally:
        db_session.close()

    return None
