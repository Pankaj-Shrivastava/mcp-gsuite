# mcp-gsuite — Edge Cases & Boundary Conditions

> **Status:** In Progress
> **Last updated:** 2026-07-13
> **Repository:** `mcp-gsuite`
> **References:** [`architecture.md`](./architecture.md) · [`implementation-plan.md`](./implementation-plan.md)

---

## Table of Contents

1. [Authentication & Identity Gate](#1-authentication--identity-gate)
2. [Gmail Tools](#2-gmail-tools)
3. [Google Docs Tools](#3-google-docs-tools)
4. [Input Validation](#4-input-validation)
5. [Google API Failures](#5-google-api-failures)
6. [Environment & Configuration](#6-environment--configuration)
7. [Transport Layer](#7-transport-layer)

---

## 1. Authentication & Identity Gate

| ID | Edge Case | Expected Behaviour | Test? |
|---|---|---|---|
| **EC-A1** | `token.json` exists but is corrupted (invalid JSON) | Raise `AuthError`; do not expose file contents in message | Unit |
| **EC-A2** | `token.json` is valid but scopes have changed since it was issued | Re-run OAuth2 flow; old token discarded | Unit |
| **EC-A3** | Token refresh fails (network down mid-refresh) | Raise `AuthError("Token refresh failed: ...")` | Unit |
| **EC-A4** | `credentials.json` exists but has wrong format (e.g. service account JSON used in OAuth2 mode) | Raise `AuthError` with descriptive message; no crash | Unit |
| **EC-A5** | `AUTHORIZED_USER_EMAIL` env var is set but has leading/trailing whitespace | Strip whitespace before hashing; still authorise correctly | Unit |
| **EC-A6** | `AUTHORIZED_USER_EMAIL` is set to an empty string | Raise `AuthError("AUTHORIZED_USER_EMAIL is not configured.")` | Unit |
| **EC-A7** | Authenticated user email has different casing (e.g. `User@Gmail.com` vs `user@gmail.com`) | Normalise both to lowercase before hashing; access granted | Unit |
| **EC-A8** | `userinfo` endpoint returns a response with no `email` field | Raise `AccessDeniedError("Access denied.")` — no detail | Unit |
| **EC-A9** | `userinfo` call times out (network issue) | Catch exception; raise `AccessDeniedError("Access denied.")` | Unit |
| **EC-A10** | `GOOGLE_CREDENTIALS_PATH` points to a file that does not exist | Raise `AuthError`; do not reveal the path in the error message | Unit |
| **EC-A11** | Two concurrent tool calls by the authorised user | Both pass independently; stateless design means no race condition | Integration |
| **EC-A12** | Service account used with `AUTH_MODE=service_account`; identity gate bypassed | `userinfo()` never called; credentials returned directly | Unit |

---

## 2. Gmail Tools

### `create_email_draft`

| ID | Edge Case | Expected Behaviour | Test? |
|---|---|---|---|
| **EC-G1** | `to` contains a comma-separated list of valid emails | All recipients included correctly in the draft | Unit |
| **EC-G2** | `to` contains one valid and one invalid email (`user@, bad`) | Raise `InvalidInputError` before any API call | Unit |
| **EC-G3** | `cc` is provided as an empty string | Treat as absent; do not include CC header | Unit |
| **EC-G4** | `subject` is an empty string | Raise `InvalidInputError` before API call | Unit |
| **EC-G5** | `body` is exactly at the 25 MB limit | Accepted; no error raised | Unit |
| **EC-G6** | `body` exceeds 25 MB by 1 byte | Raise `InvalidInputError`; no API call made | Unit |
| **EC-G7** | `body` contains Unicode / emoji characters | Encoded correctly as UTF-8 in the MIME message | Unit |
| **EC-G8** | Gmail API returns 429 (quota exceeded) | Raise `QuotaError`; do not retry automatically | Unit |
| **EC-G9** | Draft created successfully; `draft["id"]` key missing from response | Raise `MCPGSuiteError`; do not return partial result | Unit |

### `send_email`

| ID | Edge Case | Expected Behaviour | Test? |
|---|---|---|---|
| **EC-G10** | `send_email` called without `gmail.send` scope in token | Raise `PermissionError`; log missing scope at WARNING | Unit |
| **EC-G11** | Recipient email is syntactically valid but domain does not exist | Gmail API returns 400; raise `InvalidInputError` | Unit |
| **EC-G12** | `send_email` called; audit log cannot be written (disk full) | Log warning; still attempt send; do NOT silently drop the log failure | Unit |
| **EC-G13** | `body` contains HTML content when plain text expected | Sent as-is; no sanitisation; consumer is responsible for content | Unit |
| **EC-G14** | `send_email` called when Gmail account is suspended by Google | 403 response; raise `PermissionError` | Integration |

---

## 3. Google Docs Tools

### `create_document`

| ID | Edge Case | Expected Behaviour | Test? |
|---|---|---|---|
| **EC-D1** | `title` is a very long string (>1000 chars) | Google Docs API truncates title to 100 chars; server passes through result | Integration |
| **EC-D2** | `content` is an empty string | Raise `InvalidInputError` before API call | Unit |
| **EC-D3** | `content` contains special characters (`\t`, `\r\n`, Unicode) | Inserted verbatim; no normalisation | Unit |
| **EC-D4** | `documents.create` succeeds but `batchUpdate` (insertText) fails | Orphaned empty document created; raise `MCPGSuiteError`; return partial result or error — document NOT silently abandoned | Unit |
| **EC-D5** | Google Docs API quota exceeded during `create_document` | Raise `QuotaError` | Unit |
| **EC-D6** | User has reached Google Drive storage limit | 403 response from Docs API; raise `PermissionError` with message about storage | Integration |

### `append_to_document`

| ID | Edge Case | Expected Behaviour | Test? |
|---|---|---|---|
| **EC-D7** | `document_id` is an empty string | Raise `InvalidInputError` before any API call | Unit |
| **EC-D8** | `document_id` contains valid characters but document has been deleted | `documents.get` returns 404; raise `DocumentNotFoundError` | Unit |
| **EC-D9** | Document exists but caller has view-only access | `batchUpdate` returns 403; raise `PermissionError` | Unit |
| **EC-D10** | `content` is exactly at the 1 MB limit | Accepted; no error | Unit |
| **EC-D11** | `content` exceeds 1 MB by 1 byte | Raise `InvalidInputError`; no API call | Unit |
| **EC-D12** | Document is empty (new blank doc with no body content) | End index calculation must handle empty body; insert at index 1 | Unit |
| **EC-D13** | Document body has only a single newline character | End index is 2; append correctly at position 1 | Unit |
| **EC-D14** | Concurrent `append_to_document` calls on the same document | Google Docs API serialises writes; last writer wins; no corruption | Integration |
| **EC-D15** | `batchUpdate` succeeds but the subsequent `get` to retrieve `revisionId` fails | Return `revision_id: ""` with a warning log; do not fail the tool call | Unit |

---

## 4. Input Validation

| ID | Edge Case | Expected Behaviour | Test? |
|---|---|---|---|
| **EC-I1** | Any string parameter is `None` instead of a string | Raise `InvalidInputError` before API call | Unit |
| **EC-I2** | Any required string parameter is whitespace-only (`"   "`) | Treat as empty; raise `InvalidInputError` | Unit |
| **EC-I3** | Email address with quoted local part (`"user name"@domain.com`) | Accepted as valid by regex; pass to API | Unit |
| **EC-I4** | `document_id` with extra path components (`abc123/edit`) | Raise `InvalidInputError`; expect bare document ID only | Unit |

---

## 5. Google API Failures

| ID | Edge Case | Expected Behaviour |
|---|---|---|
| **EC-API1** | HTTP 500 from Google API | Raise `MCPGSuiteError`; include status code in message |
| **EC-API2** | HTTP 503 (service unavailable) | Raise `MCPGSuiteError`; suggest retry |
| **EC-API3** | DNS resolution failure for `googleapis.com` | Socket error caught; raise `MCPGSuiteError("Google API unreachable.")` |
| **EC-API4** | SSL certificate error | Raise `MCPGSuiteError`; do not bypass TLS verification |
| **EC-API5** | Response body is valid JSON but missing expected fields | Raise `MCPGSuiteError`; include which field was missing |

---

## 6. Environment & Configuration

| ID | Edge Case | Expected Behaviour |
|---|---|---|
| **EC-E1** | `.env` file is absent | Server starts but raises `AuthError` on first tool call requiring auth |
| **EC-E2** | `AUTH_MODE` is set to an unrecognised value (e.g. `"ldap"`) | Raise `AuthError("Unknown AUTH_MODE: 'ldap'")` at startup |
| **EC-E3** | `MCP_PORT` is already in use (SSE mode) | Server fails to bind; error logged; process exits with non-zero code |
| **EC-E4** | `LOG_LEVEL` is set to an invalid value | Fall back to `INFO`; log a warning about the invalid value |
| **EC-E5** | `GOOGLE_TOKEN_PATH` directory does not exist | Raise `OSError` when saving token; log warning; OAuth2 flow still returns credentials |

---

## 7. Transport Layer

| ID | Edge Case | Expected Behaviour |
|---|---|---|
| **EC-T1** | Agent closes the stdio pipe mid-call | MCP SDK raises a pipe error; server logs and exits gracefully |
| **EC-T2** | SSE client disconnects while server is waiting for Google API | Server continues the API call; result is discarded; no crash |
| **EC-T3** | Tool call JSON from agent is malformed (invalid MCP message) | MCP SDK rejects it; server returns a protocol-level error; does not crash |
| **EC-T4** | Very large tool call payload sent via SSE | Reject at transport layer before reaching handlers; raise size limit error |
