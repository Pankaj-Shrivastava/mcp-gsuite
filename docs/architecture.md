# mcp-gsuite — Architecture

> **Status:** In Progress
> **Last updated:** 2026-07-13
> **Repository:** `mcp-gsuite`

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [High-Level Architecture Diagram](#2-high-level-architecture-diagram)
3. [Component Breakdown](#3-component-breakdown)
4. [Data & Control Flow](#4-data--control-flow)
5. [Authentication Architecture](#5-authentication-architecture)
6. [Transport Layer](#6-transport-layer)
7. [Directory Structure](#7-directory-structure)
8. [Configuration & Environment](#8-configuration--environment)
9. [Constraints & Invariants](#9-constraints--invariants)
10. [Technology Stack](#10-technology-stack)
11. [Architectural Decision Records (ADRs)](#11-architectural-decision-records-adrs)

---

## 1. System Overview

`mcp-gsuite` is a **standalone MCP (Model Context Protocol) server** that acts as a trusted intermediary between AI agents and Google Workspace APIs. It centralises authentication, API communication, error handling, and retry logic for Gmail and Google Docs so that no individual agent needs to implement these concerns independently.

```
AI Agent(s)  ──MCP──►  mcp-gsuite Server  ──HTTPS──►  Google APIs
```

### Responsibilities

| Responsibility | Owner |
|---|---|
| Google OAuth2 / Service Account auth | `mcp-gsuite` server |
| Token refresh & credential caching | `mcp-gsuite` server |
| Google API call execution | `mcp-gsuite` server |
| Business / domain logic | Calling AI agent |
| Tool invocation & result consumption | Calling AI agent |

### Non-Responsibilities

- **No domain knowledge**: the server does not know what a "pulse report" or "app review" is.
- **No REST API**: all communication is exclusively via the MCP protocol.
- **No session state**: each tool call is fully self-contained and stateless.

---

## 2. High-Level Architecture Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                      AI Agent / Client                        │
│              (e.g. App Review Insights Analyser)              │
└───────────────────────────┬──────────────────────────────────┘
                            │
                   MCP Protocol (stdio / SSE)
                            │
┌───────────────────────────▼──────────────────────────────────┐
│                      mcp-gsuite Server                        │
│                                                               │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │                    Tool Registry                          │ │
│  │   (MCP SDK — tool schema registration & dispatch)        │ │
│  └──────────┬───────────────────────────────┬──────────────┘ │
│             │                               │                 │
│  ┌──────────▼──────────┐       ┌────────────▼──────────────┐ │
│  │   Gmail Handler     │       │   Google Docs Handler     │ │
│  │  src/tools/gmail.py │       │   src/tools/docs.py       │ │
│  │                     │       │                           │ │
│  │  • create_email_    │       │  • create_document        │ │
│  │    draft            │       │  • append_to_document     │ │
│  │  • send_email       │       │                           │ │
│  └──────────┬──────────┘       └────────────┬──────────────┘ │
│             │                               │                 │
│  ┌──────────▼───────────────────────────────▼──────────────┐ │
│  │                  Google Auth Layer                        │ │
│  │              src/auth/google_auth.py                      │ │
│  │                                                           │ │
│  │   OAuth2 (user account)  │  Service Account (server)     │ │
│  │   token.json caching     │  domain-wide delegation       │ │
│  └───────────────────────────┬─────────────────────────────┘ │
└───────────────────────────────┼──────────────────────────────┘
                                │ HTTPS (Google APIs)
               ┌────────────────┴────────────────┐
               │                                 │
   ┌───────────▼──────────┐         ┌────────────▼──────────┐
   │    Gmail API v1      │         │  Google Docs API v1   │
   └──────────────────────┘         └───────────────────────┘
```

---

## 3. Component Breakdown

### 3.1 MCP Server Entry Point — `src/server.py`

The top-level process that:
- Starts the MCP server using the official Python SDK (`mcp >= 1.0`).
- Registers all 4 tools with their input schemas and descriptions.
- Dispatches inbound tool calls to the appropriate handler module.
- Configures the transport layer (stdio or SSE) based on `MCP_TRANSPORT`.

### 3.2 Gmail Handler — `src/tools/gmail.py`

Implements the two Gmail-facing tools:

| Tool | Action | Gmail API Method |
|---|---|---|
| `create_email_draft` | Composes a draft, saves to Drafts folder | `users.drafts.create` |
| `send_email` | Composes and immediately delivers an email | `users.messages.send` |

Both tools accept an optional `cc` field. `send_email` is a **high-trust action** and logs recipient + subject for auditability (Constraint C4).

### 3.3 Google Docs Handler — `src/tools/docs.py`

Implements the two Docs-facing tools:

| Tool | Action | Docs API Method |
|---|---|---|
| `create_document` | Creates a new Doc with title + content | `documents.create` + `documents.batchUpdate` |
| `append_to_document` | Appends text to the end of an existing Doc | `documents.batchUpdate` (insertText) |

### 3.4 Auth Layer — `src/auth/google_auth.py`

Central credential management. Supports two modes selected via the `AUTH_MODE` environment variable:

- **OAuth2** (`oauth2`): Interactive browser flow on first run; token cached to `token.json` and auto-refreshed on subsequent calls.
- **Service Account** (`service_account`): Reads `service_account.json`; no browser interaction; suitable for server/CI deployments.

After credentials are loaded, an **identity gate** is enforced in OAuth2 mode:

1. Calls the Google `oauth2/v2/userinfo` endpoint to retrieve the authenticated email.
2. SHA-256 hashes it and compares against the SHA-256 hash of `AUTHORIZED_USER_EMAIL` (from `.env`) using `hmac.compare_digest` (constant-time — prevents timing attacks).
3. On any mismatch or error, raises `AccessDeniedError("Access denied.")` — the message is always identical regardless of failure reason, so attackers learn nothing.

Returns a ready-to-use authenticated `google.auth.credentials.Credentials` object to callers.

### 3.5 Custom Exceptions — `src/exceptions.py`

Defines structured exception classes for:
- Auth failures (expired/invalid credentials) → `AuthError`
- **Identity gate rejection** → `AccessDeniedError` (opaque: always `"Access denied."`)
- API quota errors → `QuotaError`
- Permission / scope errors → `PermissionError`
- Invalid input (e.g., malformed email, invalid document ID) → `InvalidInputError`
- Missing document → `DocumentNotFoundError`

These are surfaced as structured MCP error responses — never swallowed silently.

---

## 4. Data & Control Flow

### 4.1 Successful Tool Call (e.g. `create_document`)

```
Agent                mcp-gsuite              Google Docs API
  │                      │                         │
  │── tool_call ─────────►│                         │
  │   {title, content}    │                         │
  │                      │── load credentials ──►   │
  │                      │   google_auth.py         │
  │                      │                         │
  │                      │── documents.create ─────►│
  │                      │◄── {documentId} ─────────│
  │                      │                         │
  │                      │── documents.batchUpdate ►│
  │                      │   (insertText)           │
  │                      │◄── {revisionId} ─────────│
  │                      │                         │
  │◄── tool_result ───────│
  │   {document_id,       │
  │    document_url,      │
  │    title}             │
```

### 4.2 Auth Failure Flow

```
Agent                mcp-gsuite
  │                      │
  │── tool_call ─────────►│
  │                      │── load credentials
  │                      │   FAILS (expired / missing)
  │                      │
  │◄── tool_error ────────│
  │   {error: "AUTH_FAILURE",
  │    message: "..."}
```

### 4.3 Identity Gate — Access Denied Flow

```
Agent                mcp-gsuite              Google oauth2 API
  │                      │                         │
  │── tool_call ─────────►│                         │
  │                      │── userinfo().get() ─────►│
  │                      │◄── {email: "..."} ────────│
  │                      │                         │
  │                      │  sha256(email) vs        │
  │                      │  sha256(AUTHORIZED_USER_EMAIL)
  │                      │  hmac.compare_digest()   │
  │                      │  → MISMATCH              │
  │                      │                         │
  │◄── tool_error ────────│
  │   {error: "ACCESS_DENIED",
  │    message: "Access denied."}   ← always identical;
  │                                  attacker learns nothing
```

---

## 5. Authentication Architecture

### Auth Mode Decision Tree

```
AUTH_MODE env var
     │
     ├── "oauth2" ──────► credentials.json + token.json
     │                         │
     │                    token valid? ──────► use token
     │                    token expired? ─────► refresh (google-auth-oauthlib)
     │                    no token? ──────────► browser OAuth2 flow → save token.json
     │                         │
     │                    ── Identity Gate ──────────────────────────────────
     │                    userinfo().get() → authenticated_email
     │                    sha256(authenticated_email)
     │                      vs hmac.compare_digest
     │                    sha256(AUTHORIZED_USER_EMAIL)  ← from .env only
     │                         │
     │                    MATCH ──────────────► return credentials ✓
     │                    MISMATCH / ERROR ───► AccessDeniedError("Access denied.")
     │
     └── "service_account" ──► service_account.json
                                    │
                               domain-wide delegation
                               (identity gate skipped — service accounts
                                act as a service identity, not a personal email)
```

### OAuth2 Scopes

| Scope | Granted To | Tool(s) |
|---|---|---|
| `https://www.googleapis.com/auth/documents` | Google Docs | `create_document`, `append_to_document` |
| `https://www.googleapis.com/auth/gmail.compose` | Gmail | `create_email_draft` |
| `https://www.googleapis.com/auth/gmail.send` | Gmail | `send_email` |

> **Security note:** `gmail.send` is a sensitive scope. If only drafting is needed, remove `send_email` from tool registration and drop the `gmail.send` scope to minimise the attack surface.

### Credential File Security

| File | Purpose | Must be in `.gitignore` |
|---|---|---|
| `credentials.json` | Google Cloud OAuth2 client secret | Yes |
| `token.json` | Cached user OAuth2 token | Yes |
| `service_account.json` | Service account key | Yes |
| `.env` | Contains `AUTHORIZED_USER_EMAIL` + all secrets | Yes |

Credential paths are supplied exclusively via environment variables. They are **never** returned in tool responses (Constraint C3). The authorised email is **never hardcoded** in source — it lives exclusively in `.env`.

---

## 6. Transport Layer

The server supports two MCP transports, selectable via `MCP_TRANSPORT`:

| Transport | Use Case | Config |
|---|---|---|
| **stdio** (default) | Local agents on the same machine; simplest setup | No extra config needed |
| **SSE** (HTTP) | Remote agents connecting over a network | `MCP_HOST`, `MCP_PORT` required |

```
stdio mode:   Agent process ──stdin/stdout──► mcp-gsuite process
SSE mode:     Agent (remote) ──HTTP/SSE──────► mcp-gsuite HTTP server
```

stdio is preferred for simplicity and security (no network exposure). SSE is used when the agent and server run on separate hosts.

---

## 7. Directory Structure

```
mcp-gsuite/
├── src/
│   ├── server.py               # MCP server entry point; tool registration & dispatch
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── gmail.py            # create_email_draft, send_email
│   │   └── docs.py             # create_document, append_to_document
│   ├── auth/
│   │   ├── __init__.py
│   │   └── google_auth.py      # OAuth2 / Service Account credential loader
│   └── exceptions.py           # Structured exception classes
├── docs/
│   ├── context.md              # Full context & project specification
│   ├── architecture.md         # This file
│   ├── implementation-plan.md  # Phase-by-phase build plan
│   ├── edge-cases.md           # Edge cases & boundary conditions
│   ├── decisions.md            # Key design decisions log
│   └── eval.md                 # Evaluation criteria & test matrix
├── config/
│   └── .env.example            # Environment variable template
├── tests/
│   ├── unit/
│   │   ├── test_gmail.py       # Mocked Gmail API tests
│   │   └── test_docs.py        # Mocked Docs API tests
│   └── integration/
│       └── test_live_tools.py  # Live credential tests
├── .gitignore                  # Excludes all credential files
├── pyproject.toml
├── requirements.txt
└── README.md
```

### Module Dependency Graph

```
server.py
   ├── tools/gmail.py ──► auth/google_auth.py ──► google-auth-oauthlib
   │                  └── Gmail API v1
   ├── tools/docs.py  ──► auth/google_auth.py
   │                  └── Docs API v1
   └── exceptions.py
```

---

## 8. Configuration & Environment

All runtime configuration is provided via environment variables, typically loaded from a `.env` file.

| Variable | Required | Default | Description |
|---|---|---|---|
| `GOOGLE_CREDENTIALS_PATH` | Yes | — | Path to `credentials.json` or `service_account.json` |
| `GOOGLE_TOKEN_PATH` | No | `token.json` | Path to store/read the OAuth2 token (OAuth2 mode only) |
| `AUTH_MODE` | No | `oauth2` | Auth strategy: `oauth2` or `service_account` |
| `AUTHORIZED_USER_EMAIL` | Yes (OAuth2) | — | Email of the sole authorised user. Stored in `.env` only — never in source code |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `MCP_TRANSPORT` | No | `stdio` | MCP transport: `stdio` or `sse` |
| `MCP_HOST` | No | `127.0.0.1` | Bind host (SSE transport only — never `0.0.0.0`) |
| `MCP_PORT` | No | `8000` | Bind port (SSE transport only) |

---

## 9. Constraints & Invariants

These are hard architectural rules enforced at the server level:

| ID | Constraint | Where Enforced |
|---|---|---|
| **C1** | No domain/application logic in tool implementations | Code review + design boundary |
| **C2** | No persistent state between tool calls | Stateless handler design |
| **C3** | Credentials never returned in tool responses | Exception handling in all handlers |
| **C4** | `send_email` logs recipient + subject for auditability | `src/tools/gmail.py` |
| **C5** | Email body max 25 MB (Gmail API hard limit) | Input validation in Gmail tools |
| **C6** | `append_to_document` content max 1 MB per call | Input validation in Docs handler |
| **C7** | Identity gate error message is always `"Access denied."` — no detail leaked | `src/auth/google_auth.py` · `AccessDeniedError` |

---

## 10. Technology Stack

| Layer | Technology | Version | Rationale |
|---|---|---|---|
| Language | Python | 3.11+ | Mature MCP SDK; rich Google API library ecosystem |
| MCP Framework | `mcp` (official SDK) | >= 1.0 | Protocol compliance; self-describing tool schemas |
| Google API Client | `google-api-python-client` | latest stable | Official Google client; handles API versioning |
| Auth | `google-auth-oauthlib` | latest stable | OAuth2 flows + Service Account support |
| Transport | stdio / SSE | — | stdio default; SSE for remote/distributed agents |
| Test framework | `pytest` | latest stable | Unit + integration test suite |

---

## 11. Architectural Decision Records (ADRs)

### ADR-001: MCP over REST

**Decision:** Expose tools via MCP protocol, not a custom REST API.

**Rationale:** MCP is the standard protocol for AI agent tool use. Any MCP-compatible agent can integrate without custom adapters, and tool schemas are self-describing.

**Trade-off:** Agents must support MCP; raw HTTP clients cannot call the server directly.

---

### ADR-002: stdio as Default Transport

**Decision:** Default to stdio; SSE is opt-in.

**Rationale:** stdio requires no network configuration, avoids port management, and is the simplest pairing for agents running as sibling processes. SSE is available when distributed deployment is needed.

---

### ADR-003: Stateless Tool Design

**Decision:** Each tool call is fully self-contained with no shared state between calls.

**Rationale:** Statelessness simplifies horizontal scaling, eliminates session management bugs, and makes individual tool calls independently testable.

---

### ADR-004: Dual Auth Mode Support

**Decision:** Support both OAuth2 (user account) and Service Account auth modes.

**Rationale:** OAuth2 suits personal/developer use where a human authorises access interactively. Service Accounts suit automated server deployments without browser access. Both modes must be supported to cover the full deployment range.

---

### ADR-005: Minimal Scope Surface Area

**Decision:** Request only the exact OAuth2 scopes required by the registered tools.

**Rationale:** Minimises the blast radius of a compromised token. If `send_email` is not registered, `gmail.send` scope is not requested.

---

### ADR-006: Identity Gate via Hashed Email Comparison

**Decision:** After OAuth2 authentication, verify the authenticated user's email matches `AUTHORIZED_USER_EMAIL` using SHA-256 hashing + `hmac.compare_digest`, returning only `"Access denied."` on failure.

**Rationale:**
- The authorised email must not appear in source code (hardcoding it is a security liability in a git repo).
- Storing the raw email in a log or error message leaks it to anyone with log access.
- `hmac.compare_digest` prevents timing attacks where an attacker measures response latency to guess valid email characters.
- A single identical error message for all failure modes (wrong user, missing env var, API error) prevents the attacker from distinguishing between cases.

**Trade-off:** Identity verification adds one extra HTTP call (`userinfo`) per tool invocation in OAuth2 mode. This is acceptable because the call is fast (~50ms), the result is not cached (stateless design), and security correctness outweighs latency.
