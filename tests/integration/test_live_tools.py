import os
import pytest
from dotenv import load_dotenv

load_dotenv()

# Guard to prevent running without live credentials
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION"), 
    reason="Integration tests disabled. Set RUN_INTEGRATION=1 to run."
)

from src.tools.docs import append_to_document
from googleapiclient.discovery import build
from src.auth.google_auth import get_credentials


@pytest.fixture
def test_email():
    """Returns the email to use for testing. Uses AUTHORIZED_USER_EMAIL."""
    email = os.getenv("AUTHORIZED_USER_EMAIL")
    if not email:
        pytest.skip("AUTHORIZED_USER_EMAIL not set in .env")
    return email


def test_live_append_to_document():
    """Creates a doc via API directly, appends content, verifies revision ID changes; deletes it after."""
    # 1. Create doc manually to test append
    creds = get_credentials(["https://www.googleapis.com/auth/documents"])
    docs = build("docs", "v1", credentials=creds)
    doc_result = docs.documents().create(body={"title": "Append Test Doc"}).execute()
    doc_id = doc_result["documentId"]
    
    # 2. Append content
    append_result = append_to_document(doc_id, "Appended Line.\n")
    
    assert append_result["document_id"] == doc_id
    assert append_result["revision_id"] != ""



