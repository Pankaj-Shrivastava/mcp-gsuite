import os
import pytest

# Guard to prevent running without live credentials
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION"), 
    reason="Integration tests disabled. Set RUN_INTEGRATION=1 to run."
)

from src.tools.docs import create_document, append_to_document
from src.tools.gmail import create_email_draft, send_email
from googleapiclient.discovery import build
from src.auth.google_auth import get_credentials


@pytest.fixture
def test_email():
    """Returns the email to use for testing. Uses AUTHORIZED_USER_EMAIL."""
    email = os.getenv("AUTHORIZED_USER_EMAIL")
    if not email:
        pytest.skip("AUTHORIZED_USER_EMAIL not set in .env")
    return email


def test_live_create_document():
    """Creates a real Google Doc; asserts a valid URL is returned; deletes it after."""
    title = "Integration Test Doc"
    content = "This is a test document created by mcp-gsuite integration tests."
    
    result = create_document(title, content)
    
    assert "document_id" in result
    assert "document_url" in result
    assert result["title"] == title
    assert result["document_id"] in result["document_url"]
    
    # Cleanup
    creds = get_credentials(["https://www.googleapis.com/auth/drive"])
    drive_service = build("drive", "v3", credentials=creds)
    drive_service.files().delete(fileId=result["document_id"]).execute()


def test_live_append_to_document():
    """Creates a doc, appends content, verifies revision ID changes; deletes it after."""
    # 1. Create doc
    doc_result = create_document("Append Test Doc", "Initial Line.\n")
    doc_id = doc_result["document_id"]
    
    try:
        # 2. Append content
        append_result = append_to_document(doc_id, "Appended Line.\n")
        
        assert append_result["document_id"] == doc_id
        assert append_result["revision_id"] != ""
    finally:
        # 3. Cleanup
        creds = get_credentials(["https://www.googleapis.com/auth/drive"])
        drive_service = build("drive", "v3", credentials=creds)
        drive_service.files().delete(fileId=doc_id).execute()


def test_live_create_email_draft(test_email):
    """Creates a real Gmail draft; verifies draft_id; deletes draft after."""
    subject = "Integration Test Draft"
    body = "This is a draft from mcp-gsuite."
    
    result = create_email_draft(to=test_email, subject=subject, body=body)
    
    assert "draft_id" in result
    assert "message_id" in result
    
    # Cleanup
    creds = get_credentials(["https://www.googleapis.com/auth/gmail.compose"])
    gmail_service = build("gmail", "v1", credentials=creds)
    gmail_service.users().drafts().delete(userId="me", id=result["draft_id"]).execute()


def test_live_send_email(test_email):
    """Sends a real email to the test account; verifies message_id returned."""
    subject = "Integration Test Send"
    body = "This is a live sent email from mcp-gsuite."
    
    result = send_email(to=test_email, subject=subject, body=body)
    
    assert "message_id" in result
    assert "thread_id" in result
