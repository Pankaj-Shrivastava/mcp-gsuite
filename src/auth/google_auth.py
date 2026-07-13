"""
Google credential loader with identity-based access control.

Security design
---------------
- The authorised email is stored in the environment variable AUTHORIZED_USER_EMAIL.
  It is NEVER hardcoded in source code and NEVER included in error messages.
- Identity verification uses a constant-time HMAC comparison of the SHA-256 hash
  of the authenticated email, preventing timing-based enumeration attacks.
- Any failure — wrong user, missing env var, API error — surfaces only a single
  opaque message: "Access denied." so attackers learn nothing.
- The raw email address is never logged.
"""

import hashlib
import hmac
import logging
import os
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from src.exceptions import AccessDeniedError, AuthError

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _get_authorized_hash() -> bytes:
    """
    Read the authorised email from the environment and return its SHA-256 hash.

    The hash is computed once per call so the raw address is never stored
    beyond the scope of this function.

    Raises AuthError if the environment variable is not set — this is a
    server configuration error, not a client error.
    """
    raw = os.environ.get("AUTHORIZED_USER_EMAIL", "").strip()
    if not raw:
        raise AuthError(
            "AUTHORIZED_USER_EMAIL is not configured. "
            "Set it in your .env file."
        )
    return hashlib.sha256(raw.lower().encode()).digest()


def _verify_identity(credentials: Credentials) -> None:
    """
    Verify that the OAuth2 token belongs to the authorised user.

    Uses the OAuth2 userinfo endpoint to retrieve the authenticated email,
    then compares its hash against the authorised hash with hmac.compare_digest
    (constant-time) to prevent timing attacks.

    Raises AccessDeniedError with a generic message on any mismatch or error.
    The real email address is NEVER included in log output or exception messages.
    """
    try:
        oauth2_service = build("oauth2", "v2", credentials=credentials)
        user_info = oauth2_service.userinfo().get().execute()
        authenticated_email: Optional[str] = user_info.get("email", "")
    except Exception:
        # Network error, API error, malformed response — treat as denial.
        # Log at DEBUG only; no email details.
        logger.debug("Identity verification request failed.", exc_info=True)
        raise AccessDeniedError("Access denied.")

    if not authenticated_email:
        raise AccessDeniedError("Access denied.")

    # Constant-time comparison of SHA-256 hashes — the raw email is
    # hashed immediately and the string is not retained.
    authenticated_hash = hashlib.sha256(
        authenticated_email.lower().encode()
    ).digest()
    authorized_hash = _get_authorized_hash()

    if not hmac.compare_digest(authenticated_hash, authorized_hash):
        # Do NOT log the authenticated email — it reveals valid accounts
        # to anyone with access to log files.
        logger.warning(
            "Access denied: authenticated identity does not match authorised user."
        )
        raise AccessDeniedError("Access denied.")

    # Identity confirmed — log only that verification passed, not who passed.
    logger.info("Identity verified. Access granted.")


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def get_credentials(scopes: list[str]) -> Credentials:
    """
    Load, refresh, or obtain Google credentials for the given OAuth2 scopes,
    then verify the authenticated identity against AUTHORIZED_USER_EMAIL.

    Parameters
    ----------
    scopes:
        List of OAuth2 scope URLs required by the calling tool.

    Returns
    -------
    google.oauth2.credentials.Credentials
        A valid, unexpired credential object ready for use with Google API clients.

    Raises
    ------
    AuthError
        If credentials cannot be loaded, refreshed, or AUTHORIZED_USER_EMAIL
        is not configured.
    AccessDeniedError
        If the authenticated identity does not match the authorised user.
        Message is always "Access denied." — no further detail.
    """
    auth_mode = os.getenv("AUTH_MODE", "oauth2").lower()
    logger.info("Auth mode: %s", auth_mode)

    if auth_mode == "service_account":
        credentials = _load_service_account_credentials(scopes)
    elif auth_mode == "oauth2":
        credentials = _load_oauth2_credentials(scopes)
    else:
        raise AuthError(f"Unknown AUTH_MODE: {auth_mode!r}")

    # ── Identity gate ────────────────────────────────────────────────────────
    # Only applicable for OAuth2. Service accounts act as a service identity
    # and do not map to a personal email; skip the check in that mode.
    if auth_mode == "oauth2":
        _verify_identity(credentials)

    return credentials


def _load_oauth2_credentials(scopes: list[str]) -> Credentials:
    """OAuth2 user-account credential flow with token caching and refresh."""
    credentials_path = _require_env("GOOGLE_CREDENTIALS_PATH")
    token_path = os.getenv("GOOGLE_TOKEN_PATH", "token.json")

    creds: Optional[Credentials] = None

    # Load cached token if it exists
    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, scopes)
        except Exception as exc:
            raise AuthError(f"Failed to read token file: {exc}") from exc

    # Refresh or run the interactive flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                logger.info("OAuth2 token refreshed successfully.")
            except Exception as exc:
                raise AuthError(f"Token refresh failed: {exc}") from exc
        else:
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    credentials_path, scopes
                )
                creds = flow.run_local_server(port=0)
                logger.info("OAuth2 flow completed. Token obtained.")
            except Exception as exc:
                raise AuthError(f"OAuth2 flow failed: {exc}") from exc

        # Persist the token for subsequent runs
        try:
            with open(token_path, "w") as f:
                f.write(creds.to_json())
        except OSError as exc:
            # Non-fatal — warn but continue; next run will repeat the flow
            logger.warning("Could not save token to %s: %s", token_path, exc)

    return creds


def _load_service_account_credentials(scopes: list[str]) -> Credentials:
    """Service account credential loader."""
    credentials_path = _require_env("GOOGLE_CREDENTIALS_PATH")
    try:
        return service_account.Credentials.from_service_account_file(
            credentials_path, scopes=scopes
        )
    except Exception as exc:
        raise AuthError(f"Failed to load service account credentials: {exc}") from exc


def _require_env(name: str) -> str:
    """Return the value of a required environment variable or raise AuthError."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise AuthError(
            f"Required environment variable {name!r} is not set. "
            "Check your .env file."
        )
    return value
