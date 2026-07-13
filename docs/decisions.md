# mcp-gsuite — Design Decisions Log

> **Status:** In Progress
> **Last updated:** 2026-07-13
> **Repository:** `mcp-gsuite`
> **References:** [`architecture.md`](./architecture.md) · [`edge-cases.md`](./edge-cases.md)

This document is the authoritative log of every significant design decision made for `mcp-gsuite`, including the context, options considered, the chosen approach, and the rationale. It supplements the ADRs in `architecture.md` with finer-grained detail.

---

## Decision Index

| ID | Decision | Status | Date |
|---|---|---|---|
| D-001 | MCP over REST | Accepted | 2026-07-12 |
| D-002 | stdio as default transport | Accepted | 2026-07-12 |
| D-003 | Stateless tool design | Accepted | 2026-07-12 |
| D-004 | Dual auth mode (OAuth2 + Service Account) | Accepted | 2026-07-12 |
| D-005 | Minimal OAuth2 scope surface | Accepted | 2026-07-12 |
| D-006 | Identity gate via hashed email + hmac.compare_digest | Accepted | 2026-07-13 |
| D-007 | Authorised email stored in .env, never in source | Accepted | 2026-07-13 |
| D-008 | AccessDeniedError message is always "Access denied." | Accepted | 2026-07-13 |
| D-009 | Identity gate skipped for service account mode | Accepted | 2026-07-13 |
| D-010 | send_email is a high-trust action requiring audit logging | Accepted | 2026-07-12 |
| D-011 | No automatic retry on Google API quota errors | Accepted | 2026-07-12 |
| D-012 | append_to_document hard cap at 1 MB per call | Accepted | 2026-07-12 |

---

## D-001: MCP over REST

**Context:** The server needs to expose tools to AI agents. It could use a custom REST API, gRPC, or MCP.

**Options Considered:**
- Custom REST API — familiar, widely supported, but requires agents to implement custom client code
- gRPC — typed, efficient, but heavy for a small server and poor MCP ecosystem fit
- **MCP (Model Context Protocol)** — the emerging standard for AI agent tools

**Decision:** Use MCP exclusively.

**Rationale:** MCP is self-describing (agents discover tools via `tools/list`), has an official Python SDK, and is the protocol that consuming agents already implement. No custom adapter code needed on either side.

**Consequences:** Agents must be MCP-compatible. Raw HTTP clients cannot call the server.

---

## D-002: stdio as Default Transport

**Context:** MCP supports multiple transports. The two viable options are stdio and SSE (HTTP).

**Options Considered:**
- **stdio** — simple, zero network configuration, no port to expose
- SSE — allows remote agents but exposes a network socket

**Decision:** Default to stdio; SSE is opt-in via `MCP_TRANSPORT=sse`.

**Rationale:** stdio is the most secure option (no network exposure), simplest to configure, and is the standard pairing for agents running on the same machine. SSE is available when distributed deployment is genuinely needed.

**Consequences:** SSE users must set `MCP_HOST=127.0.0.1` (not `0.0.0.0`) and optionally add API key auth.

---

## D-003: Stateless Tool Design

**Context:** The server could maintain session state between calls (e.g. caching the last document ID) or be fully stateless.

**Options Considered:**
- Stateful — lower latency for repeated operations on the same resource; complex to implement correctly
- **Stateless** — each call is self-contained; no shared state

**Decision:** Each tool call is fully stateless.

**Rationale:** Statelessness eliminates session management bugs, makes each tool call independently testable, and avoids edge cases around stale state. Google API credentials are loaded per-call (with OS-level token file caching handling performance).

**Consequences:** A small overhead per call for credential loading (mitigated by `token.json` caching).

---

## D-004: Dual Auth Mode (OAuth2 + Service Account)

**Context:** Google APIs require authentication. Two standard approaches exist for Python applications.

**Options Considered:**
- OAuth2 only — works for personal use; requires a browser for first-time setup
- Service Account only — works for servers; requires Google Workspace admin setup
- **Both** — covers the full deployment range

**Decision:** Support both; selected by `AUTH_MODE` environment variable.

**Rationale:**
- OAuth2 is the right model for a personal developer account (the primary user of this server).
- Service Account is required for CI/CD or headless server deployments.
- The same auth interface (`get_credentials(scopes)`) serves both modes transparently.

**Consequences:** Increased implementation surface in `google_auth.py`. Mitigated by clear separation of the two code paths.

---

## D-005: Minimal OAuth2 Scope Surface

**Context:** OAuth2 tokens can be granted broad or narrow scopes.

**Decision:** Request only the exact scopes required by the tools registered at startup.

**Rationale:** A compromised token should have the minimum possible impact. If `send_email` is not registered, `gmail.send` scope is not requested, so a stolen token cannot send email.

**Implementation note:** The scope list passed to `get_credentials()` is assembled at server startup based on which tools are registered, not hardcoded globally.

---

## D-006: Identity Gate via Hashed Email + hmac.compare_digest

**Context:** The server should only respond to one specific authenticated user. The check must be both secure and attack-resistant.

**Options Considered:**
- Compare email strings directly with `==` — vulnerable to timing attacks; raw email in memory longer than needed
- Store email hash in config and compare — better, but still exposes hash in source if hardcoded
- **Hash both sides at comparison time using hmac.compare_digest** — constant-time, no raw email retained

**Decision:** Use SHA-256 hashing of both the authenticated email and `AUTHORIZED_USER_EMAIL`, compared with `hmac.compare_digest`.

**Rationale:**
- `hmac.compare_digest` is constant-time: it takes the same number of CPU cycles regardless of how many characters match, preventing timing attacks.
- SHA-256 hashing means the raw email is not retained in any variable after the comparison.
- Both sides are normalised to lowercase before hashing to handle case differences.

**Security property:** An attacker who can measure response latency at sub-millisecond precision gains zero information about the authorised email from the comparison.

---

## D-007: Authorised Email Stored in .env, Never in Source

**Context:** The authorised email address needs to be available to the server at runtime, but must not be exposed to anyone with access to the git repository.

**Options Considered:**
- Hardcode in `google_auth.py` — simple but catastrophic; visible in git history forever
- Read from a config file (not .env) — same problem unless gitignored
- **Read from `.env` environment variable** — `.env` is gitignored; only the machine operator knows its contents

**Decision:** `AUTHORIZED_USER_EMAIL` is read from the `.env` file (via `os.environ.get`). `.env` is in `.gitignore`.

**Rationale:** Environment variables are the standard mechanism for secrets in 12-factor applications. The `.env` file never touches git. The `.env.example` file contains only a placeholder (`your-google-account@gmail.com`), not the real email.

**Verification:** A pre-commit hook checking for credential leakage (`detect-secrets`) should be installed to enforce this.

---

## D-008: AccessDeniedError Message is Always "Access denied."

**Context:** When the identity gate rejects a caller, what information should the error response contain?

**Options Considered:**
- Descriptive error: `"Authenticated user X is not authorised"` — leaks the authenticated email
- Hint-based error: `"Wrong user; expected a gmail.com account"` — leaks domain information
- **Opaque error: `"Access denied."`** — reveals nothing

**Decision:** The error message is always exactly `"Access denied."` regardless of why the gate fired (wrong user, missing env var, `userinfo` API failure, empty email).

**Rationale:** Any variation in error messages between failure modes allows an attacker to enumerate states. A single static message prevents:
- Learning which email is authorised
- Learning whether the `AUTHORIZED_USER_EMAIL` env var is configured
- Distinguishing between network errors and policy rejections

**Consequences:** Legitimate debugging is harder — but this is intentional. Server operators can check `LOG_LEVEL=DEBUG` logs locally.

---

## D-009: Identity Gate Skipped for Service Account Mode

**Context:** Service accounts do not authenticate as a personal email address. They have a service account email (`name@project.iam.gserviceaccount.com`), which is not meaningful to compare against a personal Gmail address.

**Decision:** `_verify_identity()` is only called when `AUTH_MODE=oauth2`. Service account credentials skip the identity gate entirely.

**Rationale:** Service accounts represent a server identity, not a human user. The security model for service account usage is: whoever has the `service_account.json` file controls the server. The gate is therefore the file itself (gitignored + restricted permissions) rather than a runtime check.

---

## D-010: send_email is a High-Trust Action Requiring Audit Logging

**Context:** `send_email` immediately and irreversibly delivers an email. A prompt injection attack could cause an agent to send email to arbitrary recipients.

**Decision:** Before every `send_email` execution, log recipient (`to`, `cc`) and subject at `INFO` level to an audit log. The email body is NOT logged (privacy).

**Rationale:** Post-hoc review of automated sends is essential. If an agent misbehaves, the audit log provides the evidence trail. Logging the body is explicitly excluded to avoid capturing sensitive content.

**Constraint:** C4 in `architecture.md`.

---

## D-011: No Automatic Retry on Quota Errors

**Context:** Google APIs return HTTP 429 when quota is exceeded. The server could automatically retry with exponential backoff.

**Options Considered:**
- Auto-retry with backoff — transparent to callers; can cause long-running tool calls
- **Raise QuotaError immediately** — caller decides whether and when to retry

**Decision:** Raise `QuotaError` immediately on HTTP 429. No auto-retry.

**Rationale:** MCP tool calls are expected to be short-lived. A retry loop inside a tool call could block the MCP server for minutes. The calling agent is better positioned to decide the retry strategy (e.g., wait and call again vs. fail the workflow).

---

## D-012: append_to_document Hard Cap at 1 MB Per Call

**Context:** The Google Docs API processes `batchUpdate` requests entirely in memory. Very large inserts could cause memory pressure or timeouts.

**Options Considered:**
- No cap — rely on Google API to reject oversized requests
- **1 MB cap** — validated server-side before any API call

**Decision:** Reject `append_to_document` calls where `content` exceeds 1,048,576 bytes (1 MB).

**Rationale:** Failing fast with a clear `InvalidInputError` is better than a timeout or opaque API error. Callers that need to append more should split into multiple calls. 1 MB is a practical upper bound for text content (a typical novel is ~1 MB).

**Constraint:** C6 in `architecture.md`.
