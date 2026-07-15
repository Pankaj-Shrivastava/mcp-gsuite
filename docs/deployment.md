# Deploying mcp-gsuite to the Cloud

This guide covers deploying your `mcp-gsuite` MCP server to the internet using two platforms: **Railway** (recommended) and **Render** (free alternative).

## Platform Comparison

| Feature | Railway | Render (Free) |
|---|---|---|
| Cold starts | ❌ None — always on | ⚠️ 30-60s after inactivity |
| SSE support | ✅ Full support | ✅ Full support |
| Python support | ✅ Native | ✅ Native |
| Deploys from | GitHub | GitHub |
| Pricing | $5/month (includes $5 credit) | Free (750 hrs/month) |
| Free trial | 30 days / $5 credit | Always free |
| Best for | Production, reliable connections | Testing, occasional use |

> **[!IMPORTANT]**
> When deploying to the cloud, you **cannot** use `oauth2` authentication because it requires opening a local web browser to log in. You must use `service_account` mode.

> **[!WARNING]**
> **Render free tier cold starts:** After ~15 minutes of inactivity, Render spins down your service. The next connection takes 30-60 seconds to wake up, which often exceeds MCP client timeouts (causing "context deadline exceeded" errors). Use [UptimeRobot](https://uptimerobot.com/) to ping the URL every 5 minutes to keep it warm.

---

## 1. Prerequisites (Service Account)

Before deploying on either platform, create a Google Cloud Service Account:

1. Go to your [Google Cloud Console](https://console.cloud.google.com/).
2. Navigate to **IAM & Admin** > **Service Accounts**.
3. Create a new Service Account (e.g., `mcp-server-bot`).
4. Click on the newly created Service Account > **Keys** > **Add Key** > **Create new key** (JSON format).
5. Download the JSON file. This is your `service_account.json`.

*(Note: If you are using Google Workspace, your domain administrator must grant this service account Domain-Wide Delegation to act on your behalf).*

---

## 2. Push Your Code to GitHub

Both platforms deploy from a GitHub repository. Make sure your latest code is pushed:

```bash
git add .
git commit -m "Prepare for cloud deployment"
git push origin main
```

> **[!IMPORTANT]**
> Your `.gitignore` correctly excludes `service_account.json`, `.env`, `credentials.json`, and `token.json`. Never commit these — provide them as secrets through the platform dashboard.

---

## Option A: Deploy to Railway (Recommended)

Railway keeps your service **always running** with no cold starts, making it the most reliable choice for MCP servers.

### Step A1: Create an Account
1. Go to [railway.app](https://railway.app/) and sign up with your GitHub account.
2. You'll get a **30-day free trial with $5 in credits** — no credit card required.

### Step A2: Create a New Project
1. From the Railway dashboard, click **"New Project"**.
2. Select **"Deploy from GitHub repo"**.
3. Authorize Railway to access your GitHub and select the `mcp-gsuite` repository.
4. Railway auto-detects it as a Python project and uses the `Procfile` to start the server.

### Step A3: Configure Environment Variables
Go to your service's **Variables** tab and add:

| Key | Value | Description |
|---|---|---|
| `AUTH_MODE` | `service_account` | Use service account credentials. |
| `MCP_TRANSPORT` | `sse` | Expose the server via SSE over HTTP. |
| `MCP_HOST` | `0.0.0.0` | Allow Railway's network to route traffic. |
| `GOOGLE_SERVICE_ACCOUNT_PATH` | `./service_account.json` | Path to credentials file. |

> **[!NOTE]**
> You do **not** need to set `PORT` or `MCP_PORT`. Railway automatically injects `PORT`, and the server picks it up automatically.

### Step A4: Upload the Service Account Credentials

Since `service_account.json` is git-ignored, provide it via Railway's **Secret Files**:

1. In your service configuration, go to the **Settings** tab.
2. Scroll to **"Secret Files"** and click **"Add Secret File"**.
3. **Filename:** `service_account.json`
4. **Contents:** Paste the entire JSON from your downloaded service account key.

### Step A5: Generate a Public Domain
1. Go to your service's **Settings** tab.
2. Under **Networking**, click **"Generate Domain"**.
3. Railway assigns a URL like `https://mcp-gsuite-production-xxxx.up.railway.app`.

**Your MCP endpoint:**
```
https://mcp-gsuite-production-xxxx.up.railway.app/sse
```

### Step A6: Deploy
Railway auto-deploys on every push to `main`. Confirm the build by watching the logs:

```
Installing dependencies from requirements.txt...
Starting web process: python -c "from src.server import main; main()"
INFO: Started server process
INFO: Uvicorn running on http://0.0.0.0:<PORT>
```

---

## Option B: Deploy to Render (Free)

Render's free tier is a good option for testing, but be aware of cold starts (see the warning at the top).

### Step B1: Connect GitHub
1. Go to [Render.com](https://render.com/) and sign up using your GitHub account.
2. Click **New** > **Web Service**.
3. Select **"Build and deploy from a Git repository"**.
4. Connect the `mcp-gsuite` repository.

### Step B2: Configure the Service

| Setting | Value |
|---|---|
| **Name** | `mcp-gsuite` |
| **Region** | Closest to you |
| **Branch** | `main` |
| **Runtime** | `Python 3` |
| **Build Command** | `pip install -e .` |
| **Start Command** | `python -c "from src.server import main; main()"` |
| **Instance Type** | `Free` |

### Step B3: Configure Environment Variables

| Key | Value | Description |
|---|---|---|
| `AUTH_MODE` | `service_account` | Use service account credentials. |
| `MCP_TRANSPORT` | `sse` | Expose the server via SSE over HTTP. |
| `MCP_HOST` | `0.0.0.0` | Allow Render's network to route traffic. |
| `MCP_PORT` | `10000` | Port Render expects your app to bind to. |
| `PORT` | `10000` | Tells Render to route external traffic here. |
| `GOOGLE_SERVICE_ACCOUNT_PATH` | `./service_account.json` | Path to credentials file. |

### Step B4: Upload the Service Account Credentials

1. In your Render service configuration, scroll to the **Secret Files** section.
2. Click **Add Secret File**.
3. **Filename:** `service_account.json`
4. **Contents:** Paste the entire JSON from your downloaded service account key.

### Step B5: Deploy
Click **Create Web Service**. Render will build and start the server. Once done, the public URL appears in the top-left of your dashboard (e.g., `https://mcp-gsuite-xyz.onrender.com`).

**Your MCP endpoint:**
```
https://mcp-gsuite-xyz.onrender.com/sse
```

### Step B6: Keep It Warm (Avoid Cold Starts)
To prevent the 30-60s cold start timeout that breaks MCP connections:
1. Sign up for [UptimeRobot](https://uptimerobot.com/) (free).
2. Add an HTTP monitor for `https://mcp-gsuite-xyz.onrender.com/`.
3. Set interval to **every 5 minutes**.

This keeps the service warm so MCP clients can connect instantly.

---

## 3. Connecting to Your Deployed Server

Once deployed on either platform, add it to your MCP client:

### Cursor IDE `mcp.json` Config
```json
{
  "mcpServers": {
    "gsuite-mcp": {
      "url": "https://<your-deployment-url>/sse"
    }
  }
}
```

### Test from Terminal
Update the URL in `test_client.py` and run:
```bash
python test_client.py
```

---

## 4. How to Use (Appending to Documents)

Because Service Accounts on personal Google accounts do not have their own Google Drive storage quota, they cannot create new documents. This server is specifically designed to **append to existing documents**.

To use the tools:
1. **Create a Google Doc** using your personal Google account.
2. Click **Share** (top right corner).
3. Add your Service Account email (e.g., `mcp-server-bot@your-project.iam.gserviceaccount.com`) as an **Editor**.
4. Copy the **Document ID** from your browser's URL bar (the long string between `/d/` and `/edit`).
5. Ask your AI agent to append text to that specific Document ID.

---

## 5. Security Considerations for Public Deployment

By deploying this publicly, your SSE endpoint is available to the open internet.
Because `mcp-gsuite` implements a robust **stateless identity gate**, the server natively refuses unauthorized requests.

However, it is highly recommended to eventually place the endpoint behind an API Gateway, or implement an API Key wrapper on top of `src.server` if you intend to share the URL with third-party web agents.

---

## Troubleshooting

| Problem | Platform | Fix |
|---|---|---|
| `context deadline exceeded` in MCP client | Render | Cold start — wait 60s and retry, or set up UptimeRobot. |
| Build fails with `ModuleNotFoundError` | Both | Ensure `requirements.txt` includes `uvicorn[standard]` and `starlette`. |
| Deploy succeeds but no public URL | Railway | Go to Settings → Networking → Generate Domain. |
| `PORT` binding errors | Railway | Don't set `MCP_PORT`. Railway's `PORT` env var is picked up automatically. |
| Google API returns 403 | Both | Ensure `AUTH_MODE=service_account` is set and the service account JSON is correct. |
| Tool returns permission error | Both | Share the target Google Doc with the service account email as Editor. |
| Tools list is empty in MCP client | Render | Server may still be cold-starting. Open the URL in a browser first, then retry. |
