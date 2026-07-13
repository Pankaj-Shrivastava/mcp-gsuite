# mcp-gsuite — Implementation Plan

> **Status:** In Progress
> **Last updated:** 2026-07-13
> **Repository:** `mcp-gsuite`
> **References:** [`docs/context.md`](./context.md) · [`docs/architecture.md`](./architecture.md) · [`docs/edge-cases.md`](./edge-cases.md) · [`docs/decisions.md`](./decisions.md) · [`docs/eval.md`](./eval.md)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Prerequisites](#2-prerequisites)
3. [Phase 0 — Project Bootstrap](#3-phase-0--project-bootstrap)
4. [Phase 1 — Auth Layer](#4-phase-1--auth-layer)
5. [Phase 2 — Google Docs Tools](#5-phase-2--google-docs-tools)
6. [Phase 3 — Gmail Tools](#6-phase-3--gmail-tools)
7. [Phase 4 — MCP Server Wiring](#7-phase-4--mcp-server-wiring)
8. [Phase 5 — Testing & Documentation](#8-phase-5--testing--documentation)
9. [File Delivery Checklist](#9-file-delivery-checklist)
10. [Risk & Mitigation](#10-risk--mitigation)
11. [Definition of Done](#11-definition-of-done)

---

## 1. Overview

This plan describes the end-to-end implementation of `mcp-gsuite` — a standalone MCP server exposing 4 Google Workspace tools to AI agents:

| Tool | Service | Action |
|---|---|---|
| `create_document` | Google Docs | Creates a new Doc with title + content |
| `append_to_document` | Google Docs | Appends text to an existing Doc |
| `create_email_draft` | Gmail | Saves a composed email as a Gmail draft |
| `send_email` | Gmail | Immediately sends an email |

The implementation is organised into **5 sequential phases**, each ending with a verifiable milestone. Total estimated effort: **~3.5 developer-days**.

---

## 2. Prerequisites

Before starting Phase 0, ensure the following are in place:

### 2.1 Google Cloud Setup

- [ ] Google Cloud project created
- [ ] **Gmail API** enabled in the project
- [ ] **Google Docs API** enabled in the project
- [ ] OAuth2 consent screen configured (scopes: `documents`, `gmail.compose`, `gmail.send`)
- [ ] OAuth2 credentials downloaded as `credentials.json`
- [ ] *(Service Account only)* Service account created with domain-wide delegation; key downloaded as `service_account.json`

### 2.2 Local Environment

- [ ] Python 3.11+ installed
- [ ] `git` available
- [ ] A test Gmail account available for integration tests
- [ ] A test Google Drive folder available for Docs integration tests

---

## 3. Phase 0 — Project Bootstrap

**Estimate:** 0.5 days  
**Goal:** A clean, runnable Python project with correct dependencies and directory structure.

### 3.1 Repository & Git Setup

```bash
git init mcp-gsuite
cd mcp-gsuite
```

Create `.gitignore` — must include:

```
# Google credentials — NEVER commit these
credentials.json
token.json
service_account.json

# Environment file — contains AUTHORIZED_USER_EMAIL + secrets
.env

# Python
__pycache__/
*.py[cod]
.venv/
dist/
*.egg-info/
```

### 3.2 Directory Skeleton

Create the following structure (empty files where noted):

```
mcp-gsuite/
├── src/
│   ├── server.py               # empty — filled in Phase 4
│   ├── tools/
│   │   ├── __init__.py         # empty
│   │   ├── gmail.py            # empty — filled in Phase 3
│   │   └── docs.py             # empty — filled in Phase 2
│   ├── auth/
│   │   ├── __init__.py         # empty
│   │   └── google_auth.py      # empty — filled in Phase 1
│   └── exceptions.py           # empty — filled in Phase 1
├── docs/
│   ├── context.md
│   ├── architecture.md
│   ├── implementation-plan.md  # this file
│   ├── edge-cases.md
│   ├── decisions.md
│   └── eval.md
├── config/
│   └── .env.example
├── tests/
│   ├── unit/
│   │   ├── test_gmail.py       # empty — filled in Phase 3
│   │   └── test_docs.py        # empty — filled in Phase 2
│   └── integration/
│       └── test_live_tools.py  # empty — filled in Phase 5
├── .gitignore
├── pyproject.toml
├── requirements.txt
└── README.md
```

### 3.3 Python Project Configuration

**`pyproject.toml`:**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "mcp-gsuite"
version = "0.1.0"
description = "MCP server for Gmail and Google Docs integration"
requires-python = ">=3.11"
dependencies = [
    "mcp>=1.0",
    "google-api-python-client",
    "google-auth-oauthlib",
    "python-dotenv",
]

[project.optional-dependencies]
dev = ["pytest", "pytest-mock", "pytest-asyncio"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

**`requirements.txt`** (for quick pip install):

```
mcp>=1.0
google-api-python-client
google-auth-oauthlib
python-dotenv
pytest
pytest-mock
pytest-asyncio
```

**`config/.env.example`:**

```dotenv
# Required
GOOGLE_CREDENTIALS_PATH=./credentials.json

# Required (OAuth2 mode) — stored in .env only, never in source code
AUTHORIZED_USER_EMAIL=your-google-account@gmail.com

# Optional — OAuth2 mode
GOOGLE_TOKEN_PATH=./token.json

# Optional — defaults shown
AUTH_MODE=oauth2          # oauth2 | service_account
LOG_LEVEL=INFO            # DEBUG | INFO | WARNING | ERROR
MCP_TRANSPORT=stdio       # stdio | sse
MCP_HOST=127.0.0.1       # SSE only — never 0.0.0.0
MCP_PORT=8000             # SSE only
```

### 3.4 Virtual Environment & Install

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -e ".[dev]"
```

### Phase 0 Milestone

> The project installs cleanly (`pip install -e ".[dev]"` exits 0) and all directories exist.

---

## 4. Phase 1 — Auth Layer

**Estimate:** 0.5 days  
**Goal:** A working credential loader that supports both OAuth2 and Service Account modes, with unit tests.

### 4.1 Custom Exceptions — `src/exceptions.py`

Define the following exception hierarchy:

```python
class MCPGSuiteError(Exception):
    """Base exception for mcp-gsuite."""

class AuthError(MCPGSuiteError):
    """Raised when credential loading or token refresh fails."""

class AccessDeniedError(MCPGSuiteError):
    """
    Raised when the identity gate rejects the authenticated user.
    Message is ALWAYS "Access denied." — no detail leaked (Constraint C7).
    """

class QuotaError(MCPGSuiteError):
    """Raised when a Google API quota limit is exceeded."""

class PermissionError(MCPGSuiteError):
    """Raised when the account lacks a required scope/IAM permission."""

class InvalidInputError(MCPGSuiteError):
    """Raised when tool input fails validation."""

class DocumentNotFoundError(MCPGSuiteError):
    """Raised when a Google Doc ID cannot be resolved."""
```

### 4.2 Auth Module — `src/auth/google_auth.py`

Implement `get_credentials(scopes: list[str]) -> google.auth.credentials.Credentials`:

**OAuth2 mode (`AUTH_MODE=oauth2`):**

1. Read `GOOGLE_CREDENTIALS_PATH` → path to `credentials.json`.
2. Read `GOOGLE_TOKEN_PATH` (default `token.json`).
3. If `token.json` exists and is valid → load and return.
4. If expired → refresh using `google.auth.transport.requests.Request()`.
5. If no token → run `InstalledAppFlow.from_client_secrets_file(credentials_path, scopes).run_local_server(port=0)`.
6. Save refreshed/new token to `GOOGLE_TOKEN_PATH`.

**Service Account mode (`AUTH_MODE=service_account`):**

1. Read `GOOGLE_CREDENTIALS_PATH` → path to `service_account.json`.
2. Return `service_account.Credentials.from_service_account_file(path, scopes=scopes)`.

**Key behaviours:**
- Raise `AuthError` on any failure (missing file, invalid JSON, refresh failure).
- Never log credential file contents.
- Log which auth mode is active at `INFO` level on startup.

### 4.3 Unit Tests — Auth

File: `tests/unit/test_auth.py`

| Test | Description |
|---|---|
| `test_oauth2_uses_cached_token` | Mocks a valid `token.json`; asserts no browser flow triggered |
| `test_oauth2_refreshes_expired_token` | Mocks expired token; asserts `Request()` called |
| `test_oauth2_runs_flow_when_no_token` | No token file present; asserts `InstalledAppFlow` called |
| `test_service_account_loads_correctly` | Mocks `service_account.json`; asserts correct credential type |
| `test_missing_credentials_raises_auth_error` | No credentials file; asserts `AuthError` raised |
| `test_identity_gate_passes_for_authorised_user` | Mocks `userinfo()` returning authorised email hash match; asserts credentials returned |
| `test_identity_gate_rejects_wrong_user` | Mocks `userinfo()` returning a different email; asserts `AccessDeniedError("Access denied.")` |
| `test_identity_gate_rejects_on_api_error` | Mocks `userinfo()` throwing an exception; asserts `AccessDeniedError("Access denied.")` |
| `test_identity_gate_rejects_on_missing_env_var` | `AUTHORIZED_USER_EMAIL` not set; asserts `AuthError` raised |
| `test_identity_gate_skipped_for_service_account` | `AUTH_MODE=service_account`; asserts `userinfo()` never called |

### Phase 1 Milestone

> `pytest tests/unit/test_auth.py` passes all 5 tests with mocked credentials.

---

## 5. Phase 2 — Google Docs Tools

**Estimate:** 1 day  
**Goal:** `create_document` and `append_to_document` fully implemented with unit and integration tests.

### 5.1 Docs Handler — `src/tools/docs.py`

#### `create_document(title: str, content: str) -> dict`

**Implementation steps:**

1. Validate inputs: `title` and `content` must be non-empty strings.
2. Call `get_credentials(scopes=["https://www.googleapis.com/auth/documents"])`.
3. Build Docs API client: `googleapiclient.discovery.build("docs", "v1", credentials=creds)`.
4. Create empty document:
   ```python
   doc = service.documents().create(body={"title": title}).execute()
   document_id = doc["documentId"]
   ```
5. Insert content via `batchUpdate`:
   ```python
   requests = [{"insertText": {"location": {"index": 1}, "text": content}}]
   service.documents().batchUpdate(documentId=document_id, body={"requests": requests}).execute()
   ```
6. Return:
   ```python
   {
       "document_id": document_id,
       "document_url": f"https://docs.google.com/document/d/{document_id}/edit",
       "title": title,
   }
   ```
7. Catch `googleapiclient.errors.HttpError`:
   - 401/403 → raise `AuthError` or `PermissionError`
   - 429 → raise `QuotaError`
   - Other → re-raise as `MCPGSuiteError`

#### `append_to_document(document_id: str, content: str) -> dict`

**Implementation steps:**

1. Validate: `document_id` non-empty; `content` non-empty and ≤ 1 MB (Constraint C6).
2. Call `get_credentials(scopes=["https://www.googleapis.com/auth/documents"])`.
3. Build Docs API client.
4. Fetch current document to get end-of-body index:
   ```python
   doc = service.documents().get(documentId=document_id).execute()
   end_index = doc["body"]["content"][-1]["endIndex"] - 1
   ```
5. Append via `batchUpdate` with `insertText` at `end_index`.
6. Fetch updated document to get `revisionId`:
   ```python
   updated = service.documents().get(documentId=document_id).execute()
   revision_id = updated.get("revisionId", "")
   ```
7. Return:
   ```python
   {
       "document_id": document_id,
       "document_url": f"https://docs.google.com/document/d/{document_id}/edit",
       "revision_id": revision_id,
   }
   ```
8. Catch `HttpError`: 404 → raise `DocumentNotFoundError`; 401/403 → `PermissionError`; 429 → `QuotaError`.

### 5.2 Unit Tests — Docs

File: `tests/unit/test_docs.py`

| Test | Description |
|---|---|
| `test_create_document_success` | Mocks `documents().create()` and `batchUpdate()`; asserts correct return dict |
| `test_create_document_empty_title_raises` | Empty `title` → `InvalidInputError` |
| `test_create_document_empty_content_raises` | Empty `content` → `InvalidInputError` |
| `test_create_document_auth_error` | `HttpError(401)` → `AuthError` |
| `test_create_document_quota_error` | `HttpError(429)` → `QuotaError` |
| `test_append_success` | Mocks `get()` + `batchUpdate()`; asserts revision_id returned |
| `test_append_content_too_large_raises` | Content > 1 MB → `InvalidInputError` |
| `test_append_document_not_found` | `HttpError(404)` → `DocumentNotFoundError` |
| `test_append_permission_denied` | `HttpError(403)` → `PermissionError` |

### Phase 2 Milestone

> `pytest tests/unit/test_docs.py` passes all 9 tests.

---

## 6. Phase 3 — Gmail Tools

**Estimate:** 1 day  
**Goal:** `create_email_draft` and `send_email` fully implemented with unit and integration tests.

### 6.1 Gmail Handler — `src/tools/gmail.py`

#### Shared Helper: `_build_message(to, subject, body, cc=None) -> str`

Constructs a base64url-encoded RFC 2822 email message using Python's `email.mime` library. Returns the encoded string for use in the Gmail API `raw` field.

#### `create_email_draft(to: str, subject: str, body: str, cc: str | None = None) -> dict`

**Implementation steps:**

1. Validate: `to`, `subject`, `body` are non-empty. Body ≤ 25 MB (Constraint C5).
2. Call `get_credentials(scopes=["https://www.googleapis.com/auth/gmail.compose"])`.
3. Build Gmail API client: `googleapiclient.discovery.build("gmail", "v1", credentials=creds)`.
4. Build message with `_build_message(to, subject, body, cc)`.
5. Create draft:
   ```python
   draft = service.users().drafts().create(
       userId="me",
       body={"message": {"raw": encoded_message}}
   ).execute()
   ```
6. Return:
   ```python
   {
       "draft_id": draft["id"],
       "message_id": draft["message"]["id"],
   }
   ```
7. Catch `HttpError`: 401/403 → `AuthError`/`PermissionError`; 429 → `QuotaError`.

#### `send_email(to: str, subject: str, body: str, cc: str | None = None) -> dict`

> **High-trust action.** Must log recipient and subject before sending (Constraint C4).

**Implementation steps:**

1. Validate: `to`, `subject`, `body` non-empty. Body ≤ 25 MB (Constraint C5).
2. **Log** at `INFO` level: `f"send_email: to={to!r}, subject={subject!r}"` (no body content in logs).
3. Call `get_credentials(scopes=["https://www.googleapis.com/auth/gmail.send"])`.
4. Build Gmail API client.
5. Build message with `_build_message(to, subject, body, cc)`.
6. Send:
   ```python
   sent = service.users().messages().send(
       userId="me",
       body={"raw": encoded_message}
   ).execute()
   ```
7. Return:
   ```python
   {
       "message_id": sent["id"],
       "thread_id": sent["threadId"],
   }
   ```
8. Catch `HttpError`: 401/403 → `AuthError`/`PermissionError`; 429 → `QuotaError`; 400 (invalid recipient) → `InvalidInputError`.

### 6.2 Unit Tests — Gmail

File: `tests/unit/test_gmail.py`

| Test | Description |
|---|---|
| `test_create_draft_success` | Mocks `drafts().create()`; asserts `draft_id` and `message_id` returned |
| `test_create_draft_empty_to_raises` | Empty `to` → `InvalidInputError` |
| `test_create_draft_body_too_large_raises` | Body > 25 MB → `InvalidInputError` |
| `test_create_draft_with_cc` | CC field correctly included in message headers |
| `test_create_draft_auth_error` | `HttpError(401)` → `AuthError` |
| `test_send_email_success` | Mocks `messages().send()`; asserts `message_id` and `thread_id` returned |
| `test_send_email_logs_recipient` | Asserts logger called with `to` and `subject` (not body) |
| `test_send_email_invalid_recipient` | `HttpError(400)` → `InvalidInputError` |
| `test_send_email_quota_error` | `HttpError(429)` → `QuotaError` |

### Phase 3 Milestone

> `pytest tests/unit/test_gmail.py` passes all 9 tests.

---

## 7. Phase 4 — MCP Server Wiring

**Estimate:** 0.5 days  
**Goal:** All 4 tools discoverable and callable via MCP protocol from a test client.

### 7.1 Server Entry Point — `src/server.py`

**Implementation steps:**

1. Load environment variables from `.env` using `python-dotenv`.
2. Configure logging at the level specified by `LOG_LEVEL`.
3. Instantiate the MCP server:
   ```python
   from mcp.server import Server
   from mcp.server.stdio import stdio_server

   app = Server("mcp-gsuite")
   ```
4. Register all 4 tools using `@app.tool()` decorator, specifying:
   - Tool name (exact match to names in context.md)
   - Description (user-facing, from context.md §4)
   - Input schema (typed parameters matching §4 tables)
5. Inside each tool handler:
   - Call the corresponding function from `src/tools/gmail.py` or `src/tools/docs.py`
   - Catch `MCPGSuiteError` subclasses → return structured MCP error response
   - Let unexpected exceptions propagate (MCP SDK handles them as internal errors)
6. Select and start transport:
   ```python
   transport = os.getenv("MCP_TRANSPORT", "stdio")
   if transport == "stdio":
       async with stdio_server() as (read_stream, write_stream):
           await app.run(read_stream, write_stream, app.create_initialization_options())
   elif transport == "sse":
       # start SSE server on MCP_HOST:MCP_PORT
   ```

### 7.2 Tool Schema Reference

| Tool | Parameters | Returns |
|---|---|---|
| `create_document` | `title: str`, `content: str` | `document_id`, `document_url`, `title` |
| `append_to_document` | `document_id: str`, `content: str` | `document_id`, `document_url`, `revision_id` |
| `create_email_draft` | `to: str`, `subject: str`, `body: str`, `cc?: str` | `draft_id`, `message_id` |
| `send_email` | `to: str`, `subject: str`, `body: str`, `cc?: str` | `message_id`, `thread_id` |

### 7.3 Smoke Test (Manual)

Start the server and verify tool discovery:

```bash
python -m src.server
# In a separate MCP client or test script, call tools/list and verify 4 tools are returned.
```

### Phase 4 Milestone

> MCP client receives 4 tool definitions from `tools/list`. A test call to `create_document` (with mocked auth) returns the expected response structure.

---

## 8. Phase 5 — Testing & Documentation

**Estimate:** 0.5 days  
**Goal:** Full integration test pass, README complete, `.env.example` finalised.

### 8.1 Integration Tests — `tests/integration/test_live_tools.py`

> Requires real `credentials.json` / `token.json` and live API access. Not run in CI by default.

| Test | Description |
|---|---|
| `test_live_create_document` | Creates a real Google Doc; asserts a valid URL is returned; deletes it after |
| `test_live_append_to_document` | Creates a doc, appends content, verifies revision ID changes |
| `test_live_create_email_draft` | Creates a real Gmail draft; verifies `draft_id`; deletes draft after |
| `test_live_send_email` | Sends a real email to the test account; verifies `message_id` returned |

Run with:

```bash
RUN_INTEGRATION=1 pytest tests/integration/
```

Guard with: `pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="integration tests disabled")`.

### 8.2 README.md

Sections to include:

1. **What is this?** — One-paragraph description
2. **Quick Start** — Install, configure credentials, run server
3. **Configuration** — Mirror of `config/.env.example` with explanations
4. **Tools Reference** — Table of all 4 tools with parameters and return values
5. **Auth Setup** — Step-by-step: OAuth2 and Service Account paths
6. **Development** — How to run unit tests; how to run integration tests
7. **Security Notes** — Credential file handling, scope minimisation

### 8.3 End-to-End Test with Known Consumer

Connect the **App Review Insights Analyser** agent to the running `mcp-gsuite` server and verify:

- [ ] `create_document` produces a Google Doc with correct content
- [ ] `append_to_document` correctly extends an existing Doc
- [ ] `create_email_draft` appears in Gmail Drafts with correct recipients/subject

### Phase 5 Milestone

> All unit tests pass. At least `test_live_create_document`, `test_live_append_to_document`, and `test_live_create_email_draft` pass against live APIs. README is complete and reviewed.

---

## 9. File Delivery Checklist

| File | Phase | Status |
|---|---|---|
| `.gitignore` | 0 | [ ] |
| `pyproject.toml` | 0 | [ ] |
| `requirements.txt` | 0 | [ ] |
| `config/.env.example` | 0 | [ ] |
| `src/exceptions.py` | 1 | [ ] |
| `src/auth/__init__.py` | 1 | [ ] |
| `src/auth/google_auth.py` | 1 | [ ] |
| `tests/unit/test_auth.py` | 1 | [ ] |
| `src/tools/__init__.py` | 2 | [ ] |
| `src/tools/docs.py` | 2 | [ ] |
| `tests/unit/test_docs.py` | 2 | [ ] |
| `src/tools/gmail.py` | 3 | [ ] |
| `tests/unit/test_gmail.py` | 3 | [ ] |
| `src/server.py` | 4 | [ ] |
| `tests/integration/test_live_tools.py` | 5 | [ ] |
| `README.md` | 5 | [ ] |

---

## 10. Risk & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| OAuth2 browser flow unavailable in headless env | Medium | High | Use Service Account mode; document clearly in README |
| `gmail.send` scope review required by Google | Low | High | Use `gmail.compose` + manual send for MVP; escalate scope review separately |
| Google API quota exhaustion during testing | Low | Medium | Use exponential backoff wrapper; limit integration test runs |
| `append_to_document` index calculation off-by-one | Medium | Medium | Thorough unit tests with varied doc states; test on empty doc edge case |
| MCP SDK breaking changes (>=1.0) | Low | High | Pin exact `mcp` version in `pyproject.toml`; test on upgrade |
| Credential file accidentally committed | Low | Critical | `.gitignore` enforced from Phase 0; pre-commit hook recommended |

---

## 11. Definition of Done

The implementation is complete when **all** of the following are true:

- [ ] All 18 unit tests pass (`pytest tests/unit/` — 5 auth + 9 docs + 9 gmail... adjust counts as needed)
- [ ] MCP `tools/list` returns exactly 4 tools with correct schemas
- [ ] Tool calls return the exact response shapes defined in `context.md §4`
- [ ] `create_email_draft` and `send_email` never include credential data in responses
- [ ] `send_email` logs recipient + subject before every send (C4)
- [ ] `append_to_document` rejects payloads > 1 MB (C6)
- [ ] Email tools reject body > 25 MB (C5)
- [ ] `credentials.json`, `token.json`, `service_account.json` are in `.gitignore`
- [ ] Live integration tests pass for Docs and draft Gmail tools
- [ ] README provides a complete setup-to-running guide
