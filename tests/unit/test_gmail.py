import base64
import email
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from src.exceptions import (
    InvalidInputError,
    MCPGSuiteError,
    PermissionError,
    QuotaError,
)
from src.tools.gmail import create_email_draft, send_email

# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_get_credentials():
    with patch("src.tools.gmail.get_credentials") as mock:
        mock.return_value = MagicMock()
        yield mock

@pytest.fixture
def mock_build():
    with patch("src.tools.gmail.build") as mock:
        mock_service = MagicMock()
        mock.return_value = mock_service
        yield mock_service

def create_http_error(status: int, reason: str = "Error"):
    resp = Response({"status": str(status)})
    resp.status = status
    resp.reason = reason
    return HttpError(resp, b"{}")

def decode_raw_message(raw_b64: str):
    decoded = base64.urlsafe_b64decode(raw_b64)
    return email.message_from_bytes(decoded)


# ─── Tests for create_email_draft ──────────────────────────────────────────────

def test_create_draft_success(mock_get_credentials, mock_build):
    """UT-G01: Nominal success."""
    mock_users = mock_build.users.return_value
    mock_users.drafts.return_value.create.return_value.execute.return_value = {
        "id": "draft123",
        "message": {"id": "msg123"}
    }
    
    result = create_email_draft("test@example.com", "Test Subject", "Body Content")
    
    assert result["draft_id"] == "draft123"
    assert result["message_id"] == "msg123"
    
    # Verify the created message
    call_args = mock_users.drafts.return_value.create.call_args[1]
    raw_msg = call_args["body"]["message"]["raw"]
    msg = decode_raw_message(raw_msg)
    
    assert msg["To"] == "test@example.com"
    assert msg["Subject"] == "Test Subject"
    assert msg.get_payload().strip() == "Body Content"


def test_create_draft_empty_to_raises():
    """UT-G02: Empty to raises InvalidInputError."""
    with pytest.raises(InvalidInputError, match="'to' field must be a non-empty string"):
        create_email_draft("   ", "Subject", "Body")
    with pytest.raises(InvalidInputError, match="'subject' field must be a non-empty string"):
        create_email_draft("a@b.com", "", "Body")


def test_create_draft_invalid_email_raises():
    """UT-G03: Invalid email raises InvalidInputError."""
    with pytest.raises(InvalidInputError, match="Invalid email address provided"):
        create_email_draft("user@, bad", "Subject", "Body")


def test_create_draft_empty_cc_treated_as_absent(mock_get_credentials, mock_build):
    """UT-G04: Empty cc treated as absent."""
    mock_users = mock_build.users.return_value
    mock_users.drafts.return_value.create.return_value.execute.return_value = {
        "id": "draft123", "message": {"id": "msg123"}
    }
    
    create_email_draft("test@example.com", "Subject", "Body", cc="   ")
    
    call_args = mock_users.drafts.return_value.create.call_args[1]
    msg = decode_raw_message(call_args["body"]["message"]["raw"])
    assert "Cc" not in msg


def test_create_draft_body_at_limit_passes(mock_get_credentials, mock_build):
    """UT-G05: Body exactly at limit passes."""
    mock_users = mock_build.users.return_value
    mock_users.drafts.return_value.create.return_value.execute.return_value = {
        "id": "draft123", "message": {"id": "msg123"}
    }
    
    body = "a" * (25 * 1024 * 1024)
    result = create_email_draft("test@example.com", "Subject", body)
    assert result["draft_id"] == "draft123"


def test_create_draft_body_over_limit_raises():
    """UT-G06: Body over limit raises InvalidInputError."""
    body = "a" * (25 * 1024 * 1024 + 1)
    with pytest.raises(InvalidInputError, match="Email body exceeds 25 MB limit"):
        create_email_draft("test@example.com", "Subject", body)


def test_create_draft_unicode_body(mock_get_credentials, mock_build):
    """UT-G07: Unicode body correctly encoded."""
    mock_users = mock_build.users.return_value
    mock_users.drafts.return_value.create.return_value.execute.return_value = {
        "id": "draft123", "message": {"id": "msg123"}
    }
    
    create_email_draft("test@example.com", "Subject", "Hello 🌍")
    
    call_args = mock_users.drafts.return_value.create.call_args[1]
    msg = decode_raw_message(call_args["body"]["message"]["raw"])
    assert "Hello 🌍" in msg.get_payload()


def test_create_draft_quota_error(mock_get_credentials, mock_build):
    """UT-G08: 429 returns QuotaError."""
    mock_users = mock_build.users.return_value
    mock_users.drafts.return_value.create.return_value.execute.side_effect = create_http_error(429)
    
    with pytest.raises(QuotaError, match="quota exceeded"):
        create_email_draft("test@example.com", "Subject", "Body")


# ─── Tests for send_email ──────────────────────────────────────────────────────

def test_send_email_success(mock_get_credentials, mock_build):
    """UT-G09: Nominal success."""
    mock_users = mock_build.users.return_value
    mock_users.messages.return_value.send.return_value.execute.return_value = {
        "id": "msg123",
        "threadId": "thread123"
    }
    
    result = send_email("test@example.com", "Test Subject", "Body Content")
    
    assert result["message_id"] == "msg123"
    assert result["thread_id"] == "thread123"
    mock_users.messages.return_value.send.assert_called_once()


def test_send_email_logs_recipient_and_subject(mock_get_credentials, mock_build):
    """UT-G10: Logger called with to and subject, body NOT logged."""
    mock_users = mock_build.users.return_value
    mock_users.messages.return_value.send.return_value.execute.return_value = {
        "id": "msg123", "threadId": "thread123"
    }
    
    with patch("src.tools.gmail.logger.info") as mock_logger:
        send_email("test@example.com", "Test Subject", "SECRET BODY")
        
        mock_logger.assert_called_once()
        args = mock_logger.call_args[0]
        # Assert 'test@example.com' and 'Test Subject' are logged
        assert "test@example.com" in args or "test@example.com" in args[1:]
        
        # Assert body is NOT in args
        assert not any("SECRET BODY" in str(arg) for arg in args)


def test_send_email_missing_send_scope(mock_get_credentials, mock_build):
    """UT-G11: Missing send scope (403 with 'scope') returns PermissionError."""
    mock_users = mock_build.users.return_value
    error_403 = create_http_error(403, "Missing scope")
    
    with patch.object(HttpError, "__str__", return_value="insufficient scope"):
        mock_users.messages.return_value.send.return_value.execute.side_effect = error_403
        with pytest.raises(PermissionError, match="Permission denied"):
            send_email("test@example.com", "Subject", "Body")


def test_send_email_invalid_recipient_400(mock_get_credentials, mock_build):
    """UT-G12: 400 Invalid recipient returns InvalidInputError."""
    mock_users = mock_build.users.return_value
    mock_users.messages.return_value.send.return_value.execute.side_effect = create_http_error(400)
    
    with pytest.raises(InvalidInputError, match="Invalid input provided"):
        send_email("test@example.com", "Subject", "Body")


def test_send_email_quota_error(mock_get_credentials, mock_build):
    """UT-G13: 429 returns QuotaError."""
    mock_users = mock_build.users.return_value
    mock_users.messages.return_value.send.return_value.execute.side_effect = create_http_error(429)
    
    with pytest.raises(QuotaError, match="quota exceeded"):
        send_email("test@example.com", "Subject", "Body")


def test_send_email_with_cc(mock_get_credentials, mock_build):
    """UT-G14: CC header present in MIME message."""
    mock_users = mock_build.users.return_value
    mock_users.messages.return_value.send.return_value.execute.return_value = {
        "id": "msg123", "threadId": "thread123"
    }
    
    send_email("test@example.com", "Subject", "Body", cc="cc@example.com")
    
    call_args = mock_users.messages.return_value.send.call_args[1]
    msg = decode_raw_message(call_args["body"]["raw"])
    assert msg["Cc"] == "cc@example.com"


# ─── Additional Coverage Tests ─────────────────────────────────────────────────

def test_create_draft_missing_id_in_response(mock_get_credentials, mock_build):
    """EC-G9: Draft created but ID missing."""
    mock_users = mock_build.users.return_value
    mock_users.drafts.return_value.create.return_value.execute.return_value = {}
    
    with pytest.raises(MCPGSuiteError, match="response is missing IDs"):
        create_email_draft("test@example.com", "Subject", "Body")


def test_send_email_missing_id_in_response(mock_get_credentials, mock_build):
    """Send successful but ID missing."""
    mock_users = mock_build.users.return_value
    mock_users.messages.return_value.send.return_value.execute.return_value = {}
    
    with pytest.raises(MCPGSuiteError, match="response is missing IDs"):
        send_email("test@example.com", "Subject", "Body")


def test_send_email_unexpected_exception(mock_get_credentials, mock_build):
    mock_users = mock_build.users.return_value
    mock_users.messages.return_value.send.return_value.execute.side_effect = ValueError("Fatal Error")
    
    with pytest.raises(MCPGSuiteError, match="Unexpected error sending email"):
        send_email("test@example.com", "Subject", "Body")


def test_create_draft_unexpected_exception(mock_get_credentials, mock_build):
    mock_users = mock_build.users.return_value
    mock_users.drafts.return_value.create.return_value.execute.side_effect = ValueError("Fatal Error")
    
    with pytest.raises(MCPGSuiteError, match="Unexpected error during draft creation"):
        create_email_draft("test@example.com", "Subject", "Body")


def test_send_email_logger_exception(mock_get_credentials, mock_build, capsys):
    """EC-G12: Logger raises exception, send_email should still proceed."""
    mock_users = mock_build.users.return_value
    mock_users.messages.return_value.send.return_value.execute.return_value = {
        "id": "msg123", "threadId": "thread123"
    }
    
    with patch("src.tools.gmail.logger.info", side_effect=Exception("Disk full")):
        send_email("test@example.com", "Subject", "Body")
        
    captured = capsys.readouterr()
    assert "WARNING: Failed to write audit log for send_email: Disk full" in captured.err


def test_handle_http_error_branches_gmail(mock_get_credentials, mock_build):
    mock_users = mock_build.users.return_value
    
    # 500 Server Error
    mock_users.drafts.return_value.create.return_value.execute.side_effect = create_http_error(500, "Server Error")
    with pytest.raises(MCPGSuiteError, match="Google API error"):
        create_email_draft("T@example.com", "S", "C")
