# mcp-gsuite — Evaluation Criteria & Test Matrix

> **Status:** In Progress
> **Last updated:** 2026-07-13
> **Repository:** `mcp-gsuite`
> **References:** [`architecture.md`](./architecture.md) · [`edge-cases.md`](./edge-cases.md) · [`implementation-plan.md`](./implementation-plan.md)

This document defines how `mcp-gsuite` is evaluated for correctness, security, and reliability. It maps acceptance criteria to test types, tools, and pass/fail conditions.

---

## Table of Contents

1. [Evaluation Dimensions](#1-evaluation-dimensions)
2. [Unit Test Matrix](#2-unit-test-matrix)
3. [Integration Test Matrix](#3-integration-test-matrix)
4. [Security Evaluation](#4-security-evaluation)
5. [Contract Evaluation (MCP Protocol)](#5-contract-evaluation-mcp-protocol)
6. [Definition of Done](#6-definition-of-done)
7. [Running the Evaluation Suite](#7-running-the-evaluation-suite)

---

## 1. Evaluation Dimensions

| Dimension | What is Evaluated | Method |
|---|---|---|
| **Functional correctness** | Tools return the right data for valid inputs | Unit tests (mocked APIs) |
| **Input validation** | Invalid inputs are rejected before any API call | Unit tests |
| **Auth correctness** | Credentials are loaded, refreshed, and applied correctly | Unit tests + integration |
| **Identity gate** | Only the authorised user can invoke tools | Unit tests |
| **Security hardening** | Error messages leak no sensitive detail; no credential exposure | Manual + unit tests |
| **MCP protocol compliance** | Tools are discoverable; schemas match; error format is correct | Manual smoke test |
| **Live API integration** | Tools work against real Google APIs end-to-end | Integration tests |
| **Constraint compliance** | All C1–C7 constraints are enforced | Unit tests + code review |

---

## 2. Unit Test Matrix

All unit tests use `pytest` with `pytest-mock`. Google API calls are mocked using `unittest.mock.patch`.

### 2.1 Auth & Identity Gate — `tests/unit/test_auth.py`

| Test ID | Test Name | Covers | Pass Condition |
|---|---|---|---|
| UT-A01 | `test_oauth2_uses_cached_token` | EC-A1 | No browser flow; cached credentials returned |
| UT-A02 | `test_oauth2_refreshes_expired_token` | EC-A1 | `Request()` called; refreshed token returned |
| UT-A03 | `test_oauth2_runs_flow_when_no_token` | EC-A1 | `InstalledAppFlow` called; token saved |
| UT-A04 | `test_oauth2_corrupted_token_raises_auth_error` | EC-A1 | `AuthError` raised; no crash |
| UT-A05 | `test_service_account_loads_correctly` | EC-A12 | Service account credentials returned |
| UT-A06 | `test_missing_credentials_raises_auth_error` | EC-A10 | `AuthError` raised |
| UT-A07 | `test_unknown_auth_mode_raises_auth_error` | EC-E2 | `AuthError("Unknown AUTH_MODE...")` raised |
| UT-A08 | `test_identity_gate_passes_authorised_user` | D-006 | Credentials returned; no `AccessDeniedError` |
| UT-A09 | `test_identity_gate_rejects_wrong_user` | D-006, D-008 | `AccessDeniedError("Access denied.")` raised |
| UT-A10 | `test_identity_gate_case_insensitive` | EC-A7 | Uppercase email matches; access granted |
| UT-A11 | `test_identity_gate_rejects_on_userinfo_api_error` | EC-A9 | `AccessDeniedError("Access denied.")` raised |
| UT-A12 | `test_identity_gate_rejects_empty_email_in_response` | EC-A8 | `AccessDeniedError("Access denied.")` raised |
| UT-A13 | `test_identity_gate_missing_env_var` | EC-A6, EC-E1 | `AuthError` raised |
| UT-A14 | `test_identity_gate_whitespace_email_in_env` | EC-A5 | Email stripped; gate passes |
| UT-A15 | `test_identity_gate_skipped_for_service_account` | D-009 | `userinfo()` never called |

### 2.2 Google Docs Tools — `tests/unit/test_docs.py`

| Test ID | Test Name | Covers | Pass Condition |
|---|---|---|---|
| UT-D01 | `test_create_document_success` | Nominal | Returns `document_id`, `document_url`, `title` |
| UT-D02 | `test_create_document_empty_title_raises` | EC-D2 | `InvalidInputError` raised before API call |
| UT-D03 | `test_create_document_empty_content_raises` | EC-D2 | `InvalidInputError` raised before API call |
| UT-D04 | `test_create_document_auth_error_401` | EC-API1 | `AuthError` raised |
| UT-D05 | `test_create_document_quota_error_429` | EC-D5 | `QuotaError` raised |
| UT-D06 | `test_create_document_batchupdate_fails` | EC-D4 | `MCPGSuiteError` raised; no silent failure |
| UT-D07 | `test_append_to_document_success` | Nominal | Returns `document_id`, `document_url`, `revision_id` |
| UT-D08 | `test_append_empty_document_id_raises` | EC-D7 | `InvalidInputError` raised |
| UT-D09 | `test_append_document_not_found_404` | EC-D8 | `DocumentNotFoundError` raised |
| UT-D10 | `test_append_permission_denied_403` | EC-D9 | `PermissionError` raised |
| UT-D11 | `test_append_content_at_limit_passes` | EC-D10 | No error; API called |
| UT-D12 | `test_append_content_over_limit_raises` | EC-D11, C6 | `InvalidInputError` raised; no API call |
| UT-D13 | `test_append_to_empty_document` | EC-D12 | Inserts at index 1; no crash |
| UT-D14 | `test_append_revision_id_missing_in_response` | EC-D15 | `revision_id: ""`; warning logged; no exception |

### 2.3 Gmail Tools — `tests/unit/test_gmail.py`

| Test ID | Test Name | Covers | Pass Condition |
|---|---|---|---|
| UT-G01 | `test_create_draft_success` | Nominal | Returns `draft_id`, `message_id` |
| UT-G02 | `test_create_draft_empty_to_raises` | EC-G4 | `InvalidInputError` raised |
| UT-G03 | `test_create_draft_invalid_email_raises` | EC-G2 | `InvalidInputError` raised before API call |
| UT-G04 | `test_create_draft_empty_cc_treated_as_absent` | EC-G3 | No CC header in MIME message |
| UT-G05 | `test_create_draft_body_at_limit_passes` | EC-G5 | No error |
| UT-G06 | `test_create_draft_body_over_limit_raises` | EC-G6, C5 | `InvalidInputError` raised; no API call |
| UT-G07 | `test_create_draft_unicode_body` | EC-G7 | Encoded as UTF-8 in MIME message |
| UT-G08 | `test_create_draft_quota_error` | EC-G8 | `QuotaError` raised |
| UT-G09 | `test_send_email_success` | Nominal | Returns `message_id`, `thread_id` |
| UT-G10 | `test_send_email_logs_recipient_and_subject` | C4, D-010 | Logger called with `to` and `subject`; body NOT logged |
| UT-G11 | `test_send_email_missing_send_scope` | EC-G10 | `PermissionError` raised |
| UT-G12 | `test_send_email_invalid_recipient_400` | EC-G11 | `InvalidInputError` raised |
| UT-G13 | `test_send_email_quota_error` | EC-G8 | `QuotaError` raised |
| UT-G14 | `test_send_email_with_cc` | EC-G1 | CC header present in MIME message |

**Total unit tests: 43** (15 auth + 14 docs + 14 gmail)

---

## 3. Integration Test Matrix

Integration tests run against live Google APIs. They require valid credentials and are guarded by `RUN_INTEGRATION=1`.

```bash
RUN_INTEGRATION=1 pytest tests/integration/ -v
```

| Test ID | Test Name | Prerequisites | Pass Condition |
|---|---|---|---|
| IT-D01 | `test_live_create_document` | OAuth2 token; Docs API enabled | Valid URL returned; document visible in Drive |
| IT-D02 | `test_live_append_to_document` | IT-D01 passed (or existing doc ID) | `revision_id` changes; content visible in Doc |
| IT-D03 | `test_live_create_document_and_append` | OAuth2 token | Full round-trip: create then append; both succeed |
| IT-G01 | `test_live_create_email_draft` | OAuth2 token; Gmail API enabled | Draft appears in Gmail Drafts; `draft_id` returned |
| IT-G02 | `test_live_send_email` | OAuth2 token; `gmail.send` scope | Email received in test inbox; `message_id` returned |
| IT-A01 | `test_live_identity_gate_authorised` | Valid `AUTHORIZED_USER_EMAIL` in `.env` | Tool call succeeds end-to-end |
| IT-A02 | `test_live_identity_gate_wrong_user` | Different Google account credentials | `AccessDeniedError` raised; no API call to Docs/Gmail |

**Cleanup:** Each integration test must delete any documents or drafts it creates (in a `finally` block) to keep the test account clean.

---

## 4. Security Evaluation

These checks are performed manually or with static analysis tools. They are not automated unit tests.

| Check ID | Evaluation | Method | Pass Condition |
|---|---|---|---|
| SEC-01 | `AUTHORIZED_USER_EMAIL` not present in any `.py` or `.md` source file | `git grep AUTHORIZED_USER_EMAIL src/` | Zero matches |
| SEC-02 | Authenticated email never written to any log output | Code review + `grep -r "authenticated_email" src/` | Zero log statements with the variable |
| SEC-03 | `AccessDeniedError` message is always exactly `"Access denied."` | Unit tests UT-A09, UT-A11, UT-A12 | All pass |
| SEC-04 | `credentials.json`, `token.json`, `.env` are gitignored | `git check-ignore credentials.json token.json .env` | All reported as ignored |
| SEC-05 | No credential file content appears in tool responses | Code review of all tool handlers | No credential data in return dicts |
| SEC-06 | `hmac.compare_digest` used (not `==`) for email comparison | Code review of `google_auth.py` | `hmac.compare_digest` present |
| SEC-07 | `send_email` audit log does NOT include email body | UT-G10 + code review | Body absent from log statement |
| SEC-08 | `MCP_HOST` defaults to `127.0.0.1`, not `0.0.0.0` | Code review + config table | Default is `127.0.0.1` |
| SEC-09 | No known vulnerabilities in dependencies | `pip-audit` | Zero HIGH/CRITICAL findings |

---

## 5. Contract Evaluation (MCP Protocol)

Verify the server correctly implements the MCP tool contract.

| Check ID | Evaluation | Method | Pass Condition |
|---|---|---|---|
| MCP-01 | `tools/list` returns exactly 4 tool definitions | Manual: start server, call `tools/list` | 4 tools returned |
| MCP-02 | Each tool schema has correct name, description, and input types | Manual inspection of `tools/list` response | Matches `context.md §4` exactly |
| MCP-03 | Successful tool call returns correct response shape | Manual test call for each tool | Response fields match `context.md §4` |
| MCP-04 | Failed tool call returns MCP error format (not Python exception) | Trigger `InvalidInputError`; inspect response | MCP error object returned; no stack trace |
| MCP-05 | `AccessDeniedError` surfaces as MCP error (not crash) | Trigger identity gate rejection; inspect response | MCP error with `"Access denied."` message |

---

## 6. Definition of Done

The implementation is complete when **all** of the following are satisfied:

### Functional
- [ ] All 43 unit tests pass (`pytest tests/unit/` exits 0)
- [ ] MCP `tools/list` returns exactly 4 tools with correct schemas
- [ ] All 4 tool calls return the response shapes defined in `context.md §4`
- [ ] Live integration tests IT-D01, IT-D02, IT-G01 pass against real APIs

### Security
- [ ] SEC-01 through SEC-09 all pass
- [ ] `AccessDeniedError` message is exactly `"Access denied."` in all error paths (UT-A09, UT-A11, UT-A12)
- [ ] Audit log present for every `send_email` call (UT-G10)
- [ ] `credentials.json`, `token.json`, `service_account.json`, `.env` confirmed gitignored

### Constraints
- [ ] C1: No domain logic in any tool handler
- [ ] C2: No shared state between tool calls
- [ ] C3: No credential data in any tool response
- [ ] C4: `send_email` audit log fires before every send
- [ ] C5: Email body > 25 MB rejected with `InvalidInputError`
- [ ] C6: `append_to_document` content > 1 MB rejected with `InvalidInputError`
- [ ] C7: Identity gate always returns `"Access denied."` — verified by unit + code review

### Documentation
- [ ] `README.md` complete with setup-to-running guide
- [ ] `config/.env.example` has placeholder (not real) email
- [ ] All docs cross-referenced correctly

---

## 7. Running the Evaluation Suite

```bash
# Activate virtual environment
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# Run all unit tests
pytest tests/unit/ -v

# Run unit tests with coverage report
pytest tests/unit/ --cov=src --cov-report=term-missing

# Run security dependency check
pip-audit

# Run integration tests (requires live credentials + RUN_INTEGRATION=1)
RUN_INTEGRATION=1 pytest tests/integration/ -v

# Run a specific test file
pytest tests/unit/test_auth.py -v

# Run tests matching a pattern
pytest tests/unit/ -k "identity_gate" -v
```

### Coverage Target

| Module | Target Coverage |
|---|---|
| `src/auth/google_auth.py` | ≥ 90% |
| `src/tools/gmail.py` | ≥ 90% |
| `src/tools/docs.py` | ≥ 90% |
| `src/exceptions.py` | 100% |
| `src/server.py` | ≥ 70% (transport wiring is harder to unit test) |
