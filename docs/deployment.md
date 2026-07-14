# Deploying mcp-gsuite for Free

This guide explains how to deploy your `mcp-gsuite` server to the internet using a **free tier** cloud provider so that remote AI agents can access it securely. 

We will use **Render.com**, which offers a generous free tier for web services.

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

## 2. Deploying to Render.com

Render is a popular platform that builds and runs Python apps directly from your GitHub repository for free.

### Step 2.1: Connect GitHub
1. Go to [Render.com](https://render.com/) and sign up using your GitHub account.
2. Click **New** > **Web Service**.
3. Select **"Build and deploy from a Git repository"**.
4. Connect the `mcp-gsuite` repository from your GitHub account.

### Step 2.2: Configure the Service
Fill out the service details as follows:

- **Name:** `mcp-gsuite`
- **Region:** Choose the one closest to you
- **Branch:** `main`
- **Runtime:** `Python 3`
- **Build Command:** `pip install -e .`
- **Start Command:** `python -m src.server`
- **Instance Type:** `Free`

### Step 2.3: Environment Variables
Scroll down to the **Environment Variables** section and add the following keys. **This is critical for the server to work on the cloud.**

| Key | Value | Description |
|---|---|---|
| `AUTH_MODE` | `service_account` | Tells the server to use the service account. |
| `MCP_TRANSPORT` | `sse` | Exposes the server over HTTP (Server-Sent Events). |
| `MCP_HOST` | `0.0.0.0` | Allows Render's network to route traffic to your app. |
| `MCP_PORT` | `10000` | The internal port the server will bind to. |
| `PORT` | `10000` | Tells Render to route traffic to port 10000. |
| `GOOGLE_SERVICE_ACCOUNT_PATH` | `./service_account.json` | Path to the credentials file we will create below. |

### Step 2.4: Uploading the Service Account Secret
Because we git-ignored our credentials (for good reason!), we have to provide them to Render securely.

Render allows creating "Secret Files":
1. In your Render service configuration, look for the **Secret Files** section (right below Environment Variables).
2. Click **Add Secret File**.
3. **Filename:** `service_account.json`
4. **Contents:** Paste the *entire* JSON content from the service account key you downloaded in Step 1.

### Step 2.5: Deploy
Click **Create Web Service**. 
Render will now clone your repo, install the dependencies, and start the server. 

---

## 3. Connecting to your deployed Server

Once the deployment finishes, Render will provide a public URL at the top left of your dashboard (e.g., `https://mcp-gsuite-xyz.onrender.com`).

Because `mcp-gsuite` uses the `sse` transport, your MCP connection URL will be the `/sse` endpoint.

**Your MCP URL:** 
`https://mcp-gsuite-xyz.onrender.com/sse`

You can provide this URL to any remote MCP-compatible agent to allow them to securely connect to your Google Docs integration!

---

## 4. How to Use (Appending to Documents)

Because Service Accounts on personal Google accounts do not have their own Google Drive storage quota, they cannot create new documents. This server is specifically designed to **append to existing documents**.

To use the tools:
1. **Create a Google Doc** using your personal Google account.
2. Click **Share** (top right corner).
3. Add your Service Account email (e.g., `mcp-server-bot@your-project.iam.gserviceaccount.com`) as an **Editor**.
4. Copy the **Document ID** from your browser's URL bar (the long string between `/d/` and `/edit`).
5. Ask your AI agent to append text to that specific Document ID.

*(You do not need to configure the Document ID in your Render environment variables — it is passed dynamically by the AI agent when it calls the tool).*

---

## Security Considerations for Public Deployment

By deploying this publicly, your SSE endpoint is available to the open internet. 
Because `mcp-gsuite` implements a robust **stateless identity gate**, the server natively refuses unauthorized requests. 

However, it is highly recommended to eventually place the endpoint behind an API Gateway, or implement an API Key wrapper on top of `src.server` if you intend to share the URL with third-party web agents.
