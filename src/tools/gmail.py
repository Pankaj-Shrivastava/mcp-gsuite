import base64
import logging
import re
from email.message import EmailMessage
from typing import Dict, Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.auth.google_auth import get_credentials
from src.exceptions import InvalidInputError, MCPGSuiteError, PermissionError, QuotaError

logger = logging.getLogger(__name__)

COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
MAX_EMAIL_BODY_BYTES = 25 * 1024 * 1024  # 25 MB

# Basic regex for email format
EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_emails(email_string: str) -> None:
    if not isinstance(email_string, str) or not email_string.strip():
        raise InvalidInputError("Email string must not be empty.")
    
    # Check for valid emails, handle comma-separated
    emails = [e.strip() for e in email_string.split(",")]
    for e in emails:
        # Edge case: quoted local part is allowed by some standards, but our regex is simple.
        # We'll just ensure there's at least one @ and a dot after it, without spaces.
        # But EC-G3/I3 specifically says `"user name"@domain.com` might be allowed?
        # Actually a simpler check: must have @ and no whitespace unless quoted.
        # Let's use a very permissive regex just to catch obvious errors like "user@, bad" (EC-G2).
        if not re.match(r'^(".*?"|[^@\s]+)@[^@\s]+\.[^@\s]+$', e):
            raise InvalidInputError(f"Invalid email address provided: {e}")


def _build_message(to: str, subject: str, body: str, cc: Optional[str] = None) -> str:
    if not isinstance(to, str) or not to.strip():
        raise InvalidInputError("'to' field must be a non-empty string.")
    if not isinstance(subject, str) or not subject.strip():
        raise InvalidInputError("'subject' field must be a non-empty string.")
    if not isinstance(body, str):
        raise InvalidInputError("'body' field must be a string.")

    body_bytes = body.encode("utf-8")
    if len(body_bytes) > MAX_EMAIL_BODY_BYTES:
        raise InvalidInputError("Email body exceeds 25 MB limit.")

    _validate_emails(to)
    
    message = EmailMessage()
    message.set_content(body)
    message["To"] = to
    message["Subject"] = subject
    
    if cc and cc.strip():
        _validate_emails(cc)
        message["Cc"] = cc
        
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return encoded_message


def _handle_http_error(error: HttpError, action_desc: str) -> None:
    status = error.resp.status
    if status in (401, 403):
        if "quota" in str(error).lower() or "limit" in str(error).lower():
            raise QuotaError(f"Google API quota or limit exceeded during {action_desc}.")
        if "scope" in str(error).lower():
            logger.warning(f"Missing required scope during {action_desc}: {error}")
        raise PermissionError(f"Permission denied during {action_desc}. Status {status}.")
    elif status == 429:
        raise QuotaError(f"Google API quota exceeded during {action_desc}.")
    elif status == 400:
        raise InvalidInputError(f"Invalid input provided for {action_desc}: {error}")
    else:
        raise MCPGSuiteError(f"Google API error during {action_desc}: {error}")


def create_email_draft(to: str, subject: str, body: str, cc: Optional[str] = None) -> Dict[str, str]:
    """
    Creates an email draft in Gmail.
    """
    # Build and validate message first
    encoded_message = _build_message(to, subject, body, cc)
    
    creds = get_credentials([COMPOSE_SCOPE])
    service = build("gmail", "v1", credentials=creds)
    
    try:
        draft = service.users().drafts().create(
            userId="me",
            body={"message": {"raw": encoded_message}}
        ).execute()
    except HttpError as e:
        _handle_http_error(e, "draft creation")
    except Exception as e:
        raise MCPGSuiteError(f"Unexpected error during draft creation: {e}")

    if "id" not in draft or "message" not in draft or "id" not in draft["message"]:
        raise MCPGSuiteError(f"Draft created successfully but response is missing IDs: {draft}")

    return {
        "draft_id": draft["id"],
        "message_id": draft["message"]["id"],
    }


def send_email(to: str, subject: str, body: str, cc: Optional[str] = None) -> Dict[str, str]:
    """
    Immediately sends an email via Gmail.
    """
    # Build and validate message first
    encoded_message = _build_message(to, subject, body, cc)
    
    # Audit log (Constraint C4)
    try:
        logger.info("send_email: to=%r, subject=%r, cc=%r", to, subject, cc)
    except Exception as e:
        import sys
        print(f"WARNING: Failed to write audit log for send_email: {e}", file=sys.stderr)
        # Log failure must not be silently dropped (EC-G12) but we still attempt send

    creds = get_credentials([SEND_SCOPE])
    service = build("gmail", "v1", credentials=creds)
    
    try:
        sent = service.users().messages().send(
            userId="me",
            body={"raw": encoded_message}
        ).execute()
    except HttpError as e:
        _handle_http_error(e, "sending email")
    except Exception as e:
        raise MCPGSuiteError(f"Unexpected error sending email: {e}")

    if "id" not in sent or "threadId" not in sent:
        raise MCPGSuiteError(f"Email sent successfully but response is missing IDs: {sent}")

    return {
        "message_id": sent["id"],
        "thread_id": sent["threadId"],
    }
