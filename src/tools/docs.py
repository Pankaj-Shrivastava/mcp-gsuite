import logging
from typing import Any, Dict

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.auth.google_auth import get_credentials
from src.exceptions import (
    AuthError,
    DocumentNotFoundError,
    InvalidInputError,
    MCPGSuiteError,
    PermissionError,
    QuotaError,
)

logger = logging.getLogger(__name__)

DOCS_SCOPES = ["https://www.googleapis.com/auth/documents"]
MAX_APPEND_BYTES = 1 * 1024 * 1024  # 1 MB


def _handle_http_error(error: HttpError, action_desc: str) -> None:
    """Map Google API HttpErrors to specific domain exceptions."""
    status = error.resp.status
    if status in (401, 403):
        # Could be token expiry, missing scope, or storage limit
        if "quota" in str(error).lower() or "limit" in str(error).lower():
            raise QuotaError(f"Google API quota or limit exceeded during {action_desc}.")
        raise PermissionError(f"Permission denied during {action_desc}. Status {status}.")
    elif status == 429:
        raise QuotaError(f"Google API quota exceeded during {action_desc}.")
    elif status == 404:
        raise DocumentNotFoundError(f"Document not found during {action_desc}.")
    elif status == 400:
        raise InvalidInputError(f"Invalid input provided for {action_desc}: {error}")
    else:
        raise MCPGSuiteError(f"Google API error during {action_desc}: {error}")


def create_document(title: str, content: str) -> Dict[str, str]:
    """
    Creates a new Google Doc with the given title and populates it with content.
    """
    if not isinstance(title, str) or not title.strip():
        raise InvalidInputError("title must be a non-empty string.")
    if not isinstance(content, str) or not content.strip():
        raise InvalidInputError("content must be a non-empty string.")

    creds = get_credentials(DOCS_SCOPES)
    service = build("docs", "v1", credentials=creds)

    # 1. Create empty document
    try:
        doc = service.documents().create(body={"title": title}).execute()
        document_id = doc["documentId"]
    except HttpError as e:
        _handle_http_error(e, "document creation")
    except Exception as e:
        raise MCPGSuiteError(f"Unexpected error during document creation: {e}")

    # 2. Insert content
    requests = [{"insertText": {"location": {"index": 1}, "text": content}}]
    try:
        service.documents().batchUpdate(
            documentId=document_id, body={"requests": requests}
        ).execute()
    except HttpError as e:
        # Edge case: Create succeeded but append failed. The doc exists but is empty.
        # We must raise to inform the agent the content write failed.
        raise MCPGSuiteError(
            f"Document created (ID: {document_id}) but content insertion failed: {e}"
        )
    except Exception as e:
        raise MCPGSuiteError(
            f"Document created (ID: {document_id}) but unexpected error during insertion: {e}"
        )

    return {
        "document_id": document_id,
        "document_url": f"https://docs.google.com/document/d/{document_id}/edit",
        "title": title,
    }


def append_to_document(document_id: str, content: str) -> Dict[str, str]:
    """
    Appends new content to the end of an existing Google Doc.
    """
    if not isinstance(document_id, str) or not document_id.strip():
        raise InvalidInputError("document_id must be a non-empty string.")
    if not isinstance(content, str) or not content.strip():
        raise InvalidInputError("content must be a non-empty string.")

    if len(content.encode("utf-8")) > MAX_APPEND_BYTES:
        raise InvalidInputError("Append content exceeds 1 MB limit.")

    creds = get_credentials(DOCS_SCOPES)
    service = build("docs", "v1", credentials=creds)

    # 1. Fetch current document to find the end index
    try:
        doc = service.documents().get(documentId=document_id).execute()
    except HttpError as e:
        _handle_http_error(e, "fetching document")
    except Exception as e:
        raise MCPGSuiteError(f"Unexpected error fetching document: {e}")

    # Calculate end index. A blank doc has content at index 0 (a single newline, end_index 1 or 2).
    # The last element in the body contains the final newline character that cannot be modified.
    try:
        body_content = doc.get("body", {}).get("content", [])
        if not body_content:
            end_index = 1
        else:
            # Insert just before the final newline marker of the document
            end_index = body_content[-1]["endIndex"] - 1
    except (IndexError, KeyError) as e:
        logger.warning("Could not calculate end index correctly, defaulting to 1. Error: %s", e)
        end_index = 1

    # 2. Append content
    requests = [{"insertText": {"location": {"index": max(1, end_index)}, "text": content}}]
    try:
        service.documents().batchUpdate(
            documentId=document_id, body={"requests": requests}
        ).execute()
    except HttpError as e:
        _handle_http_error(e, "appending to document")
    except Exception as e:
        raise MCPGSuiteError(f"Unexpected error appending to document: {e}")

    # 3. Fetch updated document to get new revisionId
    revision_id = ""
    try:
        updated = service.documents().get(documentId=document_id).execute()
        revision_id = updated.get("revisionId", "")
    except Exception as e:
        logger.warning(
            "Content appended successfully, but failed to fetch updated revision_id: %s", e
        )
        # We do not fail the tool call here, as the primary objective (writing) succeeded.

    return {
        "document_id": document_id,
        "document_url": f"https://docs.google.com/document/d/{document_id}/edit",
        "revision_id": revision_id,
    }
