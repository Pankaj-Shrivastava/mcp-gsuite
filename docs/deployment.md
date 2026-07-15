# Deploying mcp-gsuite to Railway

This guide explains how to deploy your `mcp-gsuite` MCP server to **Railway.app** so that remote AI agents can access it over the internet.

## Why Railway?

Railway keeps your service **always running** — there are no cold starts or spin-downs like free-tier alternatives. This is critical for MCP servers because they use SSE (Server-Sent Events), which requires long-lived HTTP connections that would be killed by serverless platforms or sleeping free-tier containers.

| Feature | Railway |
|---|---|
| Cold starts | ❌ None — always on |
| SSE support | ✅ Full support |
| Python support | ✅ Native (auto-detected) |
| Deploys from | GitHub |
| Pricing | $5/month (includes $5 usage credit) |
| Free trial | 30 days / $5 credit (no card required) |

> **[!IMPORTANT]**
> When deploying to the cloud, you **cannot** use `oauth2` authentication because it requires opening a local web browser to log in. You must use `service_account` mode.

---

## 1. Prerequisites (Service Account)

Before deploying, you must create a Service Account in Google Cloud:

1. Go to your [Google Cloud Console](https://console.cloud.google.com/).
2. Navigate to **IAM & Admin** > **Service Accounts**.
3. Create a new Service Account (e.g., `mcp-server-bot`).
4. Click on the newly created Service Account > **Keys** > **Add Key** > **Create new key** (JSON format).
5. Download the JSON file. This is your `service_account.json`.

*(Note: If you are using Google Workspace, your domain administrator must grant this service account Domain-Wide Delegation to act on your behalf).*

---

## 2. Push Your Code to GitHub

Railway deploys from a GitHub repository. Make sure your latest code is pushed:

```bash
git add .
git commit -m "Prepare for Railway deployment"
git push origin main
```

> **[!IMPORTANT]**
> Your `.gitignore` excludes `service_account.json`, `.env`, `credentials.json`, and `token.json`. This is correct — we will provide these secrets through Railway's dashboard.

---

## 3. Deploy to Railway

### Step 3.1: Create an Account
1. Go to [railway.app](https://railway.app/) and sign up with your GitHub account.
2. You'll get a **30-day free trial with $5 in credits** — more than enough to test.

### Step 3.2: Create a New Project
1. From the Railway dashboard, click **"New Project"**.
2. Select **"Deploy from GitHub repo"**.
3. Authorize Railway to access your GitHub and select the `mcp-gsuite` repository.
4. Railway will auto-detect it as a Python project.

### Step 3.3: Configure Environment Variables
Before the first deploy completes, go to your service's **Variables** tab and add:

| Key | Value | Description |
|---|---|---|
| `AUTH_MODE` | `service_account` | Tells the server to use the service account (not OAuth2). |
| `MCP_TRANSPORT` | `sse` | Exposes the server over HTTP with Server-Sent Events. |
| `MCP_HOST` | `0.0.0.0` | Allows Railway's network to route traffic to your app. |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | *(see Step 3.4)* | The service account credentials. |

> **[!NOTE]**
> You do **not** need to set `PORT` or `MCP_PORT`. Railway automatically injects a `PORT` env var, and the server picks it up automatically.

### Step 3.4: Providing the Service Account Credentials

Since `service_account.json` is git-ignored (correctly), you need to get the credentials to Railway. There are two approaches:

**Option A: Inline JSON in an environment variable (Recommended)**

1. Open your local `service_account.json` file.
2. Copy the entire JSON content.
3. In Railway's Variables tab, create a new variable:
   - **Key:** `GOOGLE_SERVICE_ACCOUNT_JSON`
   - **Value:** Paste the entire JSON content.
4. The server will need a small code update to read from this env var (see Section 5).

**Option B: Commit a dummy path and use a volume**

Railway supports persistent volumes, but for a simple credentials file, Option A is simpler and more secure.

### Step 3.5: Generate a Public Domain
By default, Railway services don't have a public URL. To expose your MCP server:

1. Go to your service's **Settings** tab.
2. Under **Networking**, click **"Generate Domain"**.
3. Railway will assign a public URL like `https://mcp-gsuite-production-xxxx.up.railway.app`.

Your MCP endpoint will be:
```
https://mcp-gsuite-production-xxxx.up.railway.app/sse
```

### Step 3.6: Deploy
Railway auto-deploys on every push to `main`. You can also trigger a manual deploy from the dashboard. Watch the build logs to confirm:

```
Installing dependencies...
Starting web process: python -c "from src.server import main; main()"
INFO: Started server process
INFO: Uvicorn running on http://0.0.0.0:<PORT>
```

---

## 4. Connecting to Your Deployed Server

Once deployed, provide the SSE URL to any MCP-compatible client:

**Your MCP URL:**
```
https://mcp-gsuite-production-xxxx.up.railway.app/sse
```

### Example: Cursor IDE MCP Config
```json
{
  "mcpServers": {
    "gsuite-mcp": {
      "url": "https://mcp-gsuite-production-xxxx.up.railway.app/sse"
    }
  }
}
```

### Example: Test with the MCP test client
```bash
python test_client.py
```
*(Update the URL in `test_client.py` to your Railway URL first.)*

---

## 5. How to Use (Appending to Documents)

Because Service Accounts on personal Google accounts do not have their own Google Drive storage quota, they cannot create new documents. This server is specifically designed to **append to existing documents**.

To use the tools:
1. **Create a Google Doc** using your personal Google account.
2. Click **Share** (top right corner).
3. Add your Service Account email (e.g., `mcp-server-bot@your-project.iam.gserviceaccount.com`) as an **Editor**.
4. Copy the **Document ID** from your browser's URL bar (the long string between `/d/` and `/edit`).
5. Ask your AI agent to append text to that specific Document ID.

*(You do not need to configure the Document ID in your Railway environment variables — it is passed dynamically by the AI agent when it calls the tool).*

---

## 6. Security Considerations for Public Deployment

By deploying this publicly, your SSE endpoint is available to the open internet.
Because `mcp-gsuite` implements a robust **stateless identity gate**, the server natively refuses unauthorized requests.

However, it is highly recommended to eventually place the endpoint behind an API Gateway, or implement an API Key wrapper on top of `src.server` if you intend to share the URL with third-party web agents.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Build fails with `ModuleNotFoundError` | Ensure `requirements.txt` includes all deps (`uvicorn[standard]`, `starlette`, etc.) |
| Deploy succeeds but no public URL | Go to Settings → Networking → Generate Domain |
| `PORT` errors | Don't hardcode a port. The server reads Railway's `PORT` env var automatically. |
| Google API returns 403 | Ensure `AUTH_MODE=service_account` is set and the service account JSON is correct. |
| Tool returns permission error | Share the target Google Doc with the service account email as Editor. |
