# mcp-gsuite — Context & Architecture Document

> **Status:** Pre-implementation · Ready for Review  
> **Last updated:** 2026-07-12  
> **Repository:** `mcp-gsuite`

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Design Philosophy](#2-design-philosophy)
3. [Architecture](#3-architecture)
4. [Tool Definitions](#4-tool-definitions)
5. [Authentication & Security](#5-authentication--security)
6. [Directory Structure](#6-directory-structure)
7. [Configuration Reference](#7-configuration-reference)
8. [Constraints & Boundaries](#8-constraints--boundaries)
9. [High-Level Implementation Plan](#9-high-level-implementation-plan)
10. [Known Consumers](#10-known-consumers)

---

## 1. Project Overview

`mcp-gsuite` is a **standalone, generic MCP (Model Context Protocol) server** that provides Google Workspace integration capabilities to any AI agent. It exposes a clean, well-typed set of tools that allow agents to interact with **Gmail** and **Google Docs** without needing to handle Google API authentication, OAuth flows, or SDK specifics themselves.

### Problem It Solves

AI agents frequently need to:
- Send or draft emails as part of an automated workflow.
- Append or create structured documents for reports, summaries, or logs.

Without a shared server, every agent must independently implement Google API auth, error handling, and retry logic — creating duplication and security sprawl. `mcp-gsuite` centralises this into a single, trusted, auditable integration layer.

### What It Is NOT

- It is **not** an application-specific integration — it has no knowledge of "pulse reports", "app reviews", or any domain logic.
- It is **not** a full Google Workspace suite replacement — it exposes only the tools explicitly defined in this document.
- It is **not** a REST API — all communication is via the **Model Context Protocol (MCP)**.

---

## 2. Design Philosophy

| Principle | Application |
|---|---|
| **Generic-first** | No application-specific logic. Tools are named and designed to serve any AI agent. |
| **Minimal surface area** | Only expose what is needed. Fewer tools = fewer attack vectors and easier maintenance. |
| **Fail loudly** | Return clear, structured errors. Never silently swallow failures. |
| **Stateless tools** | Each tool call is fully self-contained. No session state between calls. |
| **Standard protocol** | Use the official MCP Python SDK (`mcp>=1.0`) for maximum compatibility. |

---

## 3. Architecture

The server is a Python application built on the **official MCP SDK**. It runs as a standalone process and communicates with clients (AI agents) via **stdio** (default) or optionally over HTTP (SSE transport for remote agents).

```
┌───────────────────────────────────────────────────────┐
│                    AI Agent / Client                   │
│         (e.g. App Review Insights Analyser)            │
└───────────────┬───────────────────────────────────────┘
                │  MCP Protocol (stdio / SSE)
┌───────────────▼───────────────────────────────────────┐
│                   mcp-gsuite Server                    │
│                                                        │
│  ┌─────────────────────┐  ┌─────────────────────────┐ │
│  │   Gmail Handler     │  │   Google Docs Handler   │ │
│  │                     │  │                         │ │
│  │  • create_draft     │  │  • create_document      │ │
│  │  • send_email       │  │  • append_to_document   │ │
│  └──────────┬──────────┘  └────────────┬────────────┘ │
│             │                          │               │
│  ┌──────────▼──────────────────────────▼────────────┐ │
│  │              Google Auth Layer                    │ │
│  │          (OAuth2 / Service Account)               │ │
│  └───────────────────────┬───────────────────────────┘ │
└──────────────────────────┼────────────────────────────┘
                           │  Google APIs (HTTPS)
              ┌────────────┴────────────┐
              │                         │
   ┌──────────▼──────────┐  ┌──────────▼──────────┐
   │   Gmail API v1      │  │  Google Docs API v1  │
   └─────────────────────┘  └─────────────────────┘
```

### Technology Stack

| Layer | Technology | Rationale |
|---|---|---|
| Language | **Python 3.11+** | Mature MCP SDK, rich Google API libraries |
| MCP SDK | **`mcp>=1.0`** | Official SDK for protocol compliance |
| Google APIs | **`google-api-python-client`** | Official Google client library |
| Auth | **`google-auth-oauthlib`** | OAuth2 + Service Account support |
| Transport | **stdio** (default), SSE (optional) | stdio is simplest; SSE for remote agents |

---

## 4. Tool Definitions

### 4.1 `create_document`

Creates a new Google Doc with the given title and populates it with the provided content.

**Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `title` | `string` | ✅ | The title of the new document. |
| `content` | `string` | ✅ | The body content to write into the document. Plain text or markdown-compatible. |

**Returns:**

| Field | Type | Description |
|---|---|---|
| `document_id` | `string` | The ID of the newly created Google Doc. |
| `document_url` | `string` | The full shareable URL of the created document. |
| `title` | `string` | Confirmed title of the document. |

**Error Cases:**
- Auth failure (invalid/expired credentials)
- Google Docs API quota exceeded
- Invalid content format

---

### 4.2 `append_to_document`

Appends new content to the end of an existing Google Doc identified by its document ID.

**Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `document_id` | `string` | ✅ | The ID of the existing Google Doc (found in its URL). |
| `content` | `string` | ✅ | The text content to append. Will be added after the last line of the document. |

**Returns:**

| Field | Type | Description |
|---|---|---|
| `document_id` | `string` | The ID of the updated document. |
| `document_url` | `string` | The URL of the updated document. |
| `revision_id` | `string` | The new revision ID after the update. |

**Error Cases:**
- Document not found (invalid `document_id`)
- Insufficient permissions to edit the document
- Auth failure

---

### 4.3 `create_email_draft`

Creates a draft email in the authenticated user's Gmail account. The draft can be reviewed and edited in Gmail before sending.

**Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `to` | `string` | ✅ | Recipient email address. Supports a single email or comma-separated list. |
| `subject` | `string` | ✅ | The subject line of the email. |
| `body` | `string` | ✅ | The body of the email. Supports plain text. |
| `cc` | `string` | ❌ | Optional CC recipients (comma-separated). |

**Returns:**

| Field | Type | Description |
|---|---|---|
| `draft_id` | `string` | The Gmail draft ID. Can be used to retrieve/send/delete the draft. |
| `message_id` | `string` | The underlying message ID of the draft. |

**Error Cases:**
- Invalid recipient email address
- Auth failure (missing `gmail.compose` scope)
- Gmail API quota exceeded

---

### 4.4 `send_email`

Immediately sends an email from the authenticated user's Gmail account.

> **⚠️ Warning:** This action is irreversible. The email will be sent immediately without any draft review step.

**Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `to` | `string` | ✅ | Recipient email address. Supports a single email or comma-separated list. |
| `subject` | `string` | ✅ | The subject line of the email. |
| `body` | `string` | ✅ | The body of the email. Supports plain text. |
| `cc` | `string` | ❌ | Optional CC recipients (comma-separated). |

**Returns:**

| Field | Type | Description |
|---|---|---|
| `message_id` | `string` | The Gmail message ID of the sent email. |
| `thread_id` | `string` | The thread ID the message belongs to. |

**Error Cases:**
- Invalid recipient email address
- Auth failure (missing `gmail.send` scope)
- Gmail API quota exceeded

---

## 5. Authentication & Security

### Required OAuth2 Scopes

| Service | Scope | Used By |
|---|---|---|
| Google Docs (read/write) | `https://www.googleapis.com/auth/documents` | `create_document`, `append_to_document` |
| Gmail (compose only) | `https://www.googleapis.com/auth/gmail.compose` | `create_email_draft` |
| Gmail (send) | `https://www.googleapis.com/auth/gmail.send` | `send_email` |

> **Note:** `gmail.send` is a sensitive scope. If only drafting is required, use only `gmail.compose` and remove the `send_email` tool to reduce scope surface area.

### Auth Methods

**Option A — OAuth2 (User Account, Recommended for personal use):**
- User authenticates via browser on first run. Token is stored locally in `token.json`.
- Subsequent calls use the refreshed token automatically.
- Credentials file: `credentials.json` (downloaded from Google Cloud Console).

**Option B — Service Account (Recommended for server deployments):**
- A service account is granted domain-wide delegation by a Google Workspace Admin.
- No browser interaction needed.
- Credentials file: `service_account.json`.

### Security Considerations

- **Never commit** `credentials.json`, `token.json`, or `service_account.json` to version control. Add to `.gitignore`.
- Credentials are loaded from the path specified in the `GOOGLE_CREDENTIALS_PATH` environment variable.
- The `send_email` tool should be treated as a **high-trust action** — agents using it should have explicit user authorization.
- Run the server with the minimum required scopes for the use case.

---

## 6. Directory Structure

```
mcp-gsuite/
├── src/
│   ├── server.py               # MCP server entry point; tool registration
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── gmail.py            # create_email_draft, send_email implementations
│   │   └── docs.py             # create_document, append_to_document implementations
│   ├── auth/
│   │   ├── __init__.py
│   │   └── google_auth.py      # OAuth2 / Service Account credential loader
│   └── exceptions.py           # Custom exception classes
├── docs/
│   └── context.md              # This file
├── config/
│   └── .env.example            # Environment variable template
├── tests/
│   ├── unit/
│   │   ├── test_gmail.py
│   │   └── test_docs.py
│   └── integration/
│       └── test_live_tools.py  # Requires live credentials
├── .gitignore
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## 7. Configuration Reference

All configuration is via environment variables (loaded from `.env`):

| Variable | Required | Default | Description |
|---|---|---|---|
| `GOOGLE_CREDENTIALS_PATH` | ✅ | — | Path to `credentials.json` or `service_account.json` |
| `GOOGLE_TOKEN_PATH` | ❌ | `token.json` | Path to store the OAuth2 token (OAuth2 mode only) |
| `AUTH_MODE` | ❌ | `oauth2` | `oauth2` or `service_account` |
| `LOG_LEVEL` | ❌ | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `MCP_TRANSPORT` | ❌ | `stdio` | `stdio` or `sse` |
| `MCP_HOST` | ❌ | `localhost` | Host for SSE transport |
| `MCP_PORT` | ❌ | `8000` | Port for SSE transport |

---

## 8. Constraints & Boundaries

| ID | Constraint | Rationale |
|---|---|---|
| **C1** | No domain logic in server tools | Tools are generic; application logic belongs in the calling agent |
| **C2** | No persistent state between tool calls | Each call is fully stateless |
| **C3** | Credentials must never be returned in tool responses | Security — credentials stay server-side |
| **C4** | `send_email` must log the recipient and subject for auditability | To allow post-hoc review of automated sends |
| **C5** | Maximum email body size: 25MB (Gmail API limit) | Hard limit imposed by the Gmail API |
| **C6** | Maximum document content: 1MB per `append` call | To prevent memory issues on large appends |

---

## 9. High-Level Implementation Plan

### Phase 0 — Project Bootstrap (0.5 days)
- Initialize Python project with `pyproject.toml`
- Set up virtual environment and install dependencies (`mcp`, `google-api-python-client`, `google-auth-oauthlib`)
- Create directory structure as defined in §6
- Set up `.gitignore` with credential files excluded

### Phase 1 — Auth Layer (0.5 days)
- Implement `src/auth/google_auth.py`
  - Support both OAuth2 (user account) and Service Account modes
  - Implement credential caching and token refresh
  - Write unit tests with mocked credentials

### Phase 2 — Google Docs Tools (1 day)
- Implement `create_document` in `src/tools/docs.py`
- Implement `append_to_document` in `src/tools/docs.py`
- Write unit tests (mocked Google API responses)
- Write live integration test (requires real credentials)

### Phase 3 — Gmail Tools (1 day)
- Implement `create_email_draft` in `src/tools/gmail.py`
- Implement `send_email` in `src/tools/gmail.py`
- Write unit tests (mocked Google API responses)
- Write live integration test (requires real credentials)

### Phase 4 — MCP Server Wiring (0.5 days)
- Implement `src/server.py` using MCP Python SDK
- Register all 4 tools with proper schemas and descriptions
- Verify tool discovery works from an MCP client

### Phase 5 — Testing & Documentation (0.5 days)
- End-to-end test with the App Review Insights Analyser as a real consumer
- Update `README.md` with setup instructions
- Add `.env.example`

---

## 10. Known Consumers

| Consumer | Tools Used | Purpose |
|---|---|---|
| **App Review Insights Analyser** | `create_document`, `append_to_document`, `create_email_draft` | Publishes weekly app review pulse reports to Google Docs and drafts summary emails |

> **Note:** The server is generic by design. To add a new consumer, simply connect it via MCP and call the appropriate tools. No changes to the server are required.
