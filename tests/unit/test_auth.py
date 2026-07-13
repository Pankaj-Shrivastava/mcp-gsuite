import os
from unittest.mock import MagicMock, patch

import pytest
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials

from src.auth.google_auth import get_credentials
from src.exceptions import AccessDeniedError, AuthError

# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_env(monkeypatch):
    """Setup a standard mock environment for auth tests."""
    monkeypatch.setenv("GOOGLE_CREDENTIALS_PATH", "dummy_creds.json")
    monkeypatch.setenv("GOOGLE_TOKEN_PATH", "dummy_token.json")
    monkeypatch.setenv("AUTHORIZED_USER_EMAIL", "test@example.com")
    monkeypatch.setenv("AUTH_MODE", "oauth2")


@pytest.fixture
def mock_userinfo():
    """Mock the Google OAuth2 userinfo endpoint."""
    with patch("src.auth.google_auth.build") as mock_build:
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        
        # Default to returning the authorised email
        mock_service.userinfo().get().execute.return_value = {"email": "test@example.com"}
        yield mock_service


# ─── Tests ─────────────────────────────────────────────────────────────────────

def test_oauth2_uses_cached_token(mock_env, mock_userinfo, monkeypatch):
    """UT-A01: Mocks a valid token.json; asserts no browser flow triggered."""
    monkeypatch.setattr("os.path.exists", lambda path: path == "dummy_token.json")
    
    mock_creds = MagicMock(spec=Credentials)
    mock_creds.valid = True
    
    with patch("src.auth.google_auth.Credentials.from_authorized_user_file", return_value=mock_creds) as mock_from_file:
        with patch("src.auth.google_auth.InstalledAppFlow") as mock_flow:
            creds = get_credentials(["scope1"])
            
            mock_from_file.assert_called_once_with("dummy_token.json", ["scope1"])
            mock_flow.assert_not_called()
            assert creds == mock_creds


def test_oauth2_refreshes_expired_token(mock_env, mock_userinfo, monkeypatch):
    """UT-A02: Mocks expired token; asserts Request() called."""
    monkeypatch.setattr("os.path.exists", lambda path: path == "dummy_token.json")
    
    mock_creds = MagicMock(spec=Credentials)
    mock_creds.valid = False
    mock_creds.expired = True
    mock_creds.refresh_token = "some_token"
    
    with patch("src.auth.google_auth.Credentials.from_authorized_user_file", return_value=mock_creds):
        with patch("src.auth.google_auth.Request") as mock_request:
            # Prevent actually writing to disk
            with patch("builtins.open"):
                creds = get_credentials(["scope1"])
                mock_creds.refresh.assert_called_once()
                assert creds == mock_creds


def test_oauth2_runs_flow_when_no_token(mock_env, mock_userinfo, monkeypatch):
    """UT-A03: No token file present; asserts InstalledAppFlow called."""
    monkeypatch.setattr("os.path.exists", lambda path: False)
    
    mock_creds = MagicMock(spec=Credentials)
    
    mock_flow_instance = MagicMock()
    mock_flow_instance.run_local_server.return_value = mock_creds
    
    with patch("src.auth.google_auth.InstalledAppFlow.from_client_secrets_file", return_value=mock_flow_instance) as mock_flow_cls:
        with patch("builtins.open"):
            creds = get_credentials(["scope1"])
            mock_flow_cls.assert_called_once_with("dummy_creds.json", ["scope1"])
            mock_flow_instance.run_local_server.assert_called_once()
            assert creds == mock_creds


def test_oauth2_corrupted_token_raises_auth_error(mock_env, monkeypatch):
    """UT-A04: AuthError raised when token reading fails; no crash."""
    monkeypatch.setattr("os.path.exists", lambda path: path == "dummy_token.json")
    
    with patch("src.auth.google_auth.Credentials.from_authorized_user_file", side_effect=Exception("Corrupted JSON")):
        with pytest.raises(AuthError, match="Failed to read token file"):
            get_credentials(["scope1"])


def test_service_account_loads_correctly(mock_env, monkeypatch):
    """UT-A05: Mocks service_account.json; asserts correct credential type."""
    monkeypatch.setenv("AUTH_MODE", "service_account")
    
    mock_creds = MagicMock(spec=ServiceAccountCredentials)
    
    with patch("src.auth.google_auth.service_account.Credentials.from_service_account_file", return_value=mock_creds) as mock_from_file:
        creds = get_credentials(["scope1"])
        mock_from_file.assert_called_once_with("dummy_creds.json", scopes=["scope1"])
        assert creds == mock_creds


def test_missing_credentials_raises_auth_error(mock_env, monkeypatch):
    """UT-A06: No credentials file path configured; asserts AuthError raised."""
    monkeypatch.delenv("GOOGLE_CREDENTIALS_PATH")
    
    with pytest.raises(AuthError, match="Required environment variable 'GOOGLE_CREDENTIALS_PATH' is not set"):
        get_credentials(["scope1"])


def test_unknown_auth_mode_raises_auth_error(mock_env, monkeypatch):
    """UT-A07: Unknown AUTH_MODE raises AuthError."""
    monkeypatch.setenv("AUTH_MODE", "ldap")
    
    with pytest.raises(AuthError, match="Unknown AUTH_MODE: 'ldap'"):
        get_credentials(["scope1"])


def test_identity_gate_passes_authorised_user(mock_env, mock_userinfo, monkeypatch):
    """UT-A08: Mocks userinfo() returning authorised email hash match; asserts credentials returned."""
    monkeypatch.setattr("os.path.exists", lambda path: path == "dummy_token.json")
    mock_creds = MagicMock(spec=Credentials)
    mock_creds.valid = True
    
    with patch("src.auth.google_auth.Credentials.from_authorized_user_file", return_value=mock_creds):
        creds = get_credentials(["scope1"])
        assert creds == mock_creds


def test_identity_gate_rejects_wrong_user(mock_env, mock_userinfo, monkeypatch):
    """UT-A09: Mocks userinfo() returning a different email; asserts AccessDeniedError."""
    monkeypatch.setattr("os.path.exists", lambda path: path == "dummy_token.json")
    mock_creds = MagicMock(spec=Credentials)
    mock_creds.valid = True
    
    mock_userinfo.userinfo().get().execute.return_value = {"email": "hacker@example.com"}
    
    with patch("src.auth.google_auth.Credentials.from_authorized_user_file", return_value=mock_creds):
        with pytest.raises(AccessDeniedError, match="^Access denied.$"):
            get_credentials(["scope1"])


def test_identity_gate_case_insensitive(mock_env, mock_userinfo, monkeypatch):
    """UT-A10: Uppercase email matches; access granted."""
    monkeypatch.setattr("os.path.exists", lambda path: path == "dummy_token.json")
    monkeypatch.setenv("AUTHORIZED_USER_EMAIL", "Test@Example.COM")
    mock_creds = MagicMock(spec=Credentials)
    mock_creds.valid = True
    
    # Return different case from API
    mock_userinfo.userinfo().get().execute.return_value = {"email": "tEsT@eXaMpLe.com"}
    
    with patch("src.auth.google_auth.Credentials.from_authorized_user_file", return_value=mock_creds):
        creds = get_credentials(["scope1"])
        assert creds == mock_creds


def test_identity_gate_rejects_on_userinfo_api_error(mock_env, mock_userinfo, monkeypatch):
    """UT-A11: Mocks userinfo() throwing an exception; asserts AccessDeniedError."""
    monkeypatch.setattr("os.path.exists", lambda path: path == "dummy_token.json")
    mock_creds = MagicMock(spec=Credentials)
    mock_creds.valid = True
    
    mock_userinfo.userinfo().get().execute.side_effect = Exception("API down")
    
    with patch("src.auth.google_auth.Credentials.from_authorized_user_file", return_value=mock_creds):
        with pytest.raises(AccessDeniedError, match="^Access denied.$"):
            get_credentials(["scope1"])


def test_identity_gate_rejects_empty_email_in_response(mock_env, mock_userinfo, monkeypatch):
    """UT-A12: Mocks userinfo() returning empty email; asserts AccessDeniedError."""
    monkeypatch.setattr("os.path.exists", lambda path: path == "dummy_token.json")
    mock_creds = MagicMock(spec=Credentials)
    mock_creds.valid = True
    
    mock_userinfo.userinfo().get().execute.return_value = {}
    
    with patch("src.auth.google_auth.Credentials.from_authorized_user_file", return_value=mock_creds):
        with pytest.raises(AccessDeniedError, match="^Access denied.$"):
            get_credentials(["scope1"])


def test_identity_gate_missing_env_var(mock_env, mock_userinfo, monkeypatch):
    """UT-A13: AUTHORIZED_USER_EMAIL not set; asserts AuthError raised."""
    monkeypatch.setattr("os.path.exists", lambda path: path == "dummy_token.json")
    monkeypatch.delenv("AUTHORIZED_USER_EMAIL")
    mock_creds = MagicMock(spec=Credentials)
    mock_creds.valid = True
    
    with patch("src.auth.google_auth.Credentials.from_authorized_user_file", return_value=mock_creds):
        with pytest.raises(AuthError, match="AUTHORIZED_USER_EMAIL is not configured"):
            get_credentials(["scope1"])


def test_identity_gate_whitespace_email_in_env(mock_env, mock_userinfo, monkeypatch):
    """UT-A14: Email stripped; gate passes."""
    monkeypatch.setattr("os.path.exists", lambda path: path == "dummy_token.json")
    monkeypatch.setenv("AUTHORIZED_USER_EMAIL", "  test@example.com   ")
    mock_creds = MagicMock(spec=Credentials)
    mock_creds.valid = True
    
    with patch("src.auth.google_auth.Credentials.from_authorized_user_file", return_value=mock_creds):
        creds = get_credentials(["scope1"])
        assert creds == mock_creds


def test_identity_gate_skipped_for_service_account(mock_env, mock_userinfo, monkeypatch):
    """UT-A15: AUTH_MODE=service_account; asserts userinfo() never called."""
    monkeypatch.setenv("AUTH_MODE", "service_account")
    
    mock_creds = MagicMock(spec=ServiceAccountCredentials)
    
    with patch("src.auth.google_auth.service_account.Credentials.from_service_account_file", return_value=mock_creds):
        creds = get_credentials(["scope1"])
        assert creds == mock_creds
        mock_userinfo.userinfo().get().execute.assert_not_called()
