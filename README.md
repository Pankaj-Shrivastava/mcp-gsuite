# mcp-gsuite

`mcp-gsuite` is a secure, stateless Model Context Protocol (MCP) server that exposes powerful Google Workspace capabilities—specifically Gmail and Google Docs—to AI agents. It leverages a rigorous identity gate to ensure that only authorized users can perform actions, preventing unauthorized usage even if the server is exposed.

## Features

- **Google Docs Integration:** Create new documents and append content to existing ones (up to 1MB per call).
- **Gmail Integration:** Create email drafts or send live emails directly (up to 25MB).
- **Identity Gate:** Uses constant-time hashing to cryptographically verify the authenticated user matches the authorized owner.
- **Audit Logging:** Logs all outgoing email headers (To, CC, Subject) for transparent auditing (body content is explicitly omitted).
- **Dual Auth Modes:** Supports both personal developer accounts (OAuth2) and headless deployments (Service Accounts).
- **Stateless:** Every tool call loads credentials and runs independently, removing class-level state risks.

---

## Quick Start

### 1. Prerequisites
- Python 3.11+
- A Google Cloud Project with the **Gmail API** and **Google Docs API** enabled.
- OAuth 2.0 Client credentials (or a Service Account key) downloaded as `credentials.json`.

### 2. Installation

```bash
git clone https://github.com/Pankaj-Shrivastava/mcp-gsuite.git
cd mcp-gsuite

# Setup virtual environment
python -m venv .venv
# Activate (Windows): .venv\Scripts\activate
# Activate (macOS/Linux): source .venv/bin/activate

# Install package
pip install -e ".[dev]"
```

### 3. Configuration
Copy the example environment file and edit it:
```bash
cp config/.env.example .env
```
Ensure you configure the `AUTHORIZED_USER_EMAIL` in `.env` to match your Google account. This is the only account that will be allowed to execute tools!

### 4. Running the Server

**Using the MCP CLI (Recommended for Development):**
```bash
mcp dev src.server:app
```

**Running manually for MCP Client Integration (stdio):**
```bash
python -m src.server
```

---

## Configuration Reference (`.env`)

| Variable | Description | Default |
|---|---|---|
| `GOOGLE_CREDENTIALS_PATH` | Path to your downloaded `credentials.json` | `./credentials.json` |
| `AUTHORIZED_USER_EMAIL` | **(Required)** The exact Google email address allowed to invoke tools. Checked securely at runtime. | N/A |
| `GOOGLE_TOKEN_PATH` | Path where the OAuth token will be cached. | `./token.json` |
| `AUTH_MODE` | Set to `oauth2` for personal use or `service_account` for headless deployments. | `oauth2` |
| `LOG_LEVEL` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |
| `MCP_TRANSPORT` | Protocol transport layer: `stdio` (local) or `sse` (network) | `stdio` |
| `MCP_HOST` / `MCP_PORT` | Bound IP and port when using `sse` transport. | `127.0.0.1` / `8000` |

---

## Tools Reference

| Tool | Parameters | Description |
|---|---|---|
| `create_document` | `title: str`, `content: str` | Creates a new Google Doc with the given title and populates it with content. Returns `document_url`. |
| `append_to_document` | `document_id: str`, `content: str` | Appends text to an existing Doc (max 1 MB per call). |
| `create_email_draft` | `to: str`, `subject: str`, `body: str`, `cc: str` (Optional) | Saves a composed email as a draft in Gmail. |
| `send_email` | `to: str`, `subject: str`, `body: str`, `cc: str` (Optional) | Immediately sends an email. **Note:** Generates an audit log containing the subject and recipient. |

---

## Security Model

The server enforces **7 core constraints** outlined in our `docs/architecture.md`. 
Highlights include:
- The server does not log sensitive credential file data or email body content.
- Opaque identity gate rejections (`AccessDeniedError`) return `"Access denied."` with zero detail to prevent enumeration attacks.
- Outbound API calls respect hard-capped payload sizes to avoid memory floods or excessive API billing.
