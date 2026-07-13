from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from src.exceptions import (
    DocumentNotFoundError,
    InvalidInputError,
    MCPGSuiteError,
    PermissionError,
    QuotaError,
)
from src.tools.docs import append_to_document, create_document

# ─── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_get_credentials():
    with patch("src.tools.docs.get_credentials") as mock:
        mock.return_value = MagicMock()
        yield mock


@pytest.fixture
def mock_build():
    with patch("src.tools.docs.build") as mock:
        mock_service = MagicMock()
        mock.return_value = mock_service
        yield mock_service


def create_http_error(status: int, reason: str = "Error"):
    resp = Response({"status": str(status)})
    resp.status = status
    resp.reason = reason
    return HttpError(resp, b"{}")


# ─── Tests for create_document ─────────────────────────────────────────────────


def test_create_document_success(mock_get_credentials, mock_build):
    """UT-D01: Nominal success."""
    mock_docs = mock_build.documents.return_value
    mock_docs.create.return_value.execute.return_value = {"documentId": "doc123"}
    mock_docs.batchUpdate.return_value.execute.return_value = {}

    result = create_document("Test Doc", "Hello World")
    
    assert result["document_id"] == "doc123"
    assert result["title"] == "Test Doc"
    assert "doc123" in result["document_url"]
    
    # Assert API calls were made correctly
    mock_docs.create.assert_called_once_with(body={"title": "Test Doc"})
    mock_docs.batchUpdate.assert_called_once_with(
        documentId="doc123",
        body={"requests": [{"insertText": {"location": {"index": 1}, "text": "Hello World"}}]},
    )


def test_create_document_empty_title_raises():
    """UT-D02: InvalidInputError on empty title."""
    with pytest.raises(InvalidInputError, match="title must be a non-empty string"):
        create_document("   ", "content")
    with pytest.raises(InvalidInputError):
        create_document(None, "content")


def test_create_document_empty_content_raises():
    """UT-D03: InvalidInputError on empty content."""
    with pytest.raises(InvalidInputError, match="content must be a non-empty string"):
        create_document("Title", "")


def test_create_document_auth_error_401(mock_get_credentials, mock_build):
    """UT-D04: 401 returns PermissionError (handled in _handle_http_error)."""
    mock_docs = mock_build.documents.return_value
    mock_docs.create.return_value.execute.side_effect = create_http_error(401)
    
    with pytest.raises(PermissionError, match="Permission denied"):
        create_document("Title", "Content")


def test_create_document_quota_error_429(mock_get_credentials, mock_build):
    """UT-D05: 429 quota error returns QuotaError."""
    mock_docs = mock_build.documents.return_value
    mock_docs.create.return_value.execute.side_effect = create_http_error(429)
    
    with pytest.raises(QuotaError, match="quota exceeded"):
        create_document("Title", "Content")


def test_create_document_batchupdate_fails(mock_get_credentials, mock_build):
    """UT-D06: create succeeds, batchUpdate fails -> MCPGSuiteError."""
    mock_docs = mock_build.documents.return_value
    mock_docs.create.return_value.execute.return_value = {"documentId": "doc123"}
    mock_docs.batchUpdate.return_value.execute.side_effect = create_http_error(500)
    
    with pytest.raises(MCPGSuiteError, match="Document created \\(ID: doc123\\) but content insertion failed"):
        create_document("Title", "Content")


# ─── Tests for append_to_document ──────────────────────────────────────────────


def test_append_to_document_success(mock_get_credentials, mock_build):
    """UT-D07: Nominal success."""
    mock_docs = mock_build.documents.return_value
    
    # 1. First get to find end_index
    mock_docs.get.return_value.execute.side_effect = [
        {"body": {"content": [{"endIndex": 1}, {"endIndex": 15}]}},  # First call
        {"revisionId": "rev123"}  # Second call
    ]
    
    result = append_to_document("doc123", "New Content")
    
    assert result["document_id"] == "doc123"
    assert result["revision_id"] == "rev123"
    assert "doc123" in result["document_url"]
    
    # Assert correct index calculated: 15 - 1 = 14
    mock_docs.batchUpdate.assert_called_once_with(
        documentId="doc123",
        body={"requests": [{"insertText": {"location": {"index": 14}, "text": "New Content"}}]},
    )


def test_append_empty_document_id_raises():
    """UT-D08: InvalidInputError on empty doc ID."""
    with pytest.raises(InvalidInputError, match="document_id must be a non-empty string"):
        append_to_document("", "content")


def test_append_document_not_found_404(mock_get_credentials, mock_build):
    """UT-D09: 404 on get returns DocumentNotFoundError."""
    mock_docs = mock_build.documents.return_value
    mock_docs.get.return_value.execute.side_effect = create_http_error(404)
    
    with pytest.raises(DocumentNotFoundError, match="Document not found"):
        append_to_document("bad_id", "content")


def test_append_permission_denied_403(mock_get_credentials, mock_build):
    """UT-D10: 403 on get returns PermissionError."""
    mock_docs = mock_build.documents.return_value
    mock_docs.get.return_value.execute.side_effect = create_http_error(403)
    
    with pytest.raises(PermissionError, match="Permission denied"):
        append_to_document("doc123", "content")


def test_append_content_at_limit_passes(mock_get_credentials, mock_build):
    """UT-D11: Content exactly at limit (1MB)."""
    mock_docs = mock_build.documents.return_value
    mock_docs.get.return_value.execute.side_effect = [
        {"body": {"content": [{"endIndex": 2}]}},
        {"revisionId": "rev"}
    ]
    
    content = "a" * (1024 * 1024)
    result = append_to_document("doc123", content)
    assert result["document_id"] == "doc123"


def test_append_content_over_limit_raises():
    """UT-D12: Content > 1MB limit raises InvalidInputError."""
    content = "a" * (1024 * 1024 + 1)
    with pytest.raises(InvalidInputError, match="Append content exceeds 1 MB limit"):
        append_to_document("doc123", content)


def test_append_to_empty_document(mock_get_credentials, mock_build):
    """UT-D13: Empty doc structure defaults to index 1."""
    mock_docs = mock_build.documents.return_value
    
    # Missing body/content entirely
    mock_docs.get.return_value.execute.side_effect = [
        {}, 
        {"revisionId": "rev1"}
    ]
    
    append_to_document("doc123", "Content")
    
    # Index 1 fallback
    mock_docs.batchUpdate.assert_called_once_with(
        documentId="doc123",
        body={"requests": [{"insertText": {"location": {"index": 1}, "text": "Content"}}]},
    )


def test_append_revision_id_missing_in_response(mock_get_credentials, mock_build):
    """UT-D14: batchUpdate succeeds but second get fails; returns empty revision_id, no crash."""
    mock_docs = mock_build.documents.return_value
    
    mock_docs.get.return_value.execute.side_effect = [
        {"body": {"content": [{"endIndex": 2}]}},  # First get (success)
        Exception("Network glitch")                # Second get (failure)
    ]
    
    result = append_to_document("doc123", "Content")
    
    # Doesn't crash, returns empty string for revision_id
    assert result["revision_id"] == ""


def test_create_document_unexpected_exception(mock_get_credentials, mock_build):
    mock_docs = mock_build.documents.return_value
    mock_docs.create.return_value.execute.side_effect = ValueError("Network weirdness")
    with pytest.raises(MCPGSuiteError, match="Unexpected error during document creation"):
        create_document("Title", "Content")


def test_create_document_batchupdate_unexpected_exception(mock_get_credentials, mock_build):
    mock_docs = mock_build.documents.return_value
    mock_docs.create.return_value.execute.return_value = {"documentId": "doc123"}
    mock_docs.batchUpdate.return_value.execute.side_effect = ValueError("Corrupt body")
    with pytest.raises(MCPGSuiteError, match="unexpected error during insertion"):
        create_document("Title", "Content")


def test_append_document_get_unexpected_exception(mock_get_credentials, mock_build):
    mock_docs = mock_build.documents.return_value
    mock_docs.get.return_value.execute.side_effect = ValueError("Unknown error")
    with pytest.raises(MCPGSuiteError, match="Unexpected error fetching document"):
        append_to_document("doc123", "Content")


def test_append_document_batchupdate_unexpected_exception(mock_get_credentials, mock_build):
    mock_docs = mock_build.documents.return_value
    mock_docs.get.return_value.execute.return_value = {"body": {"content": [{"endIndex": 2}]}}
    mock_docs.batchUpdate.return_value.execute.side_effect = ValueError("Failed")
    with pytest.raises(MCPGSuiteError, match="Unexpected error appending to document"):
        append_to_document("doc123", "Content")


def test_append_document_invalid_body_format_fallback(mock_get_credentials, mock_build):
    # Triggers IndexError / KeyError fallback (lines 118-120)
    mock_docs = mock_build.documents.return_value
    mock_docs.get.return_value.execute.side_effect = [
        {"body": {"content": [{}]}},  # Missing 'endIndex' key
        {"revisionId": "rev123"}
    ]
    append_to_document("doc123", "Content")
    mock_docs.batchUpdate.assert_called_once_with(
        documentId="doc123",
        body={"requests": [{"insertText": {"location": {"index": 1}, "text": "Content"}}]}
    )


def test_handle_http_error_branches(mock_get_credentials, mock_build):
    mock_docs = mock_build.documents.return_value
    
    # 403 with 'quota' string
    error_403 = create_http_error(403, "Storage limit reached")
    with patch.object(HttpError, "__str__", return_value="storage quota exceeded"):
        mock_docs.create.return_value.execute.side_effect = error_403
        with pytest.raises(QuotaError, match="quota or limit exceeded"):
            create_document("T", "C")
            
    # 400 Bad Request
    mock_docs.create.return_value.execute.side_effect = create_http_error(400, "Bad Request")
    with pytest.raises(InvalidInputError, match="Invalid input provided"):
        create_document("T", "C")

    # 500 Server Error
    mock_docs.create.return_value.execute.side_effect = create_http_error(500, "Server Error")
    with pytest.raises(MCPGSuiteError, match="Google API error"):
        create_document("T", "C")

