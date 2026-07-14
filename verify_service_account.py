"""
Service Account Verification Script
====================================
Checks that your service account has all the must-haves
for the mcp-gsuite server to work correctly.
"""

import json
import sys
import os

# Fix Windows console encoding for unicode characters
sys.stdout.reconfigure(encoding='utf-8')

def check(label, passed, detail=""):
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"  {status}  {label}")
    if detail:
        print(f"           {detail}")
    return passed

def main():
    sa_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "./service_account.json")
    print(f"\n{'='*60}")
    print(f"  Service Account Verification")
    print(f"{'='*60}\n")

    all_passed = True

    # ── 1. File exists ──────────────────────────────────────────
    print("[1/6] Service Account File")
    if not check("File exists", os.path.exists(sa_path), f"Path: {sa_path}"):
        print("\n  ⛔ Cannot continue without the service account file.")
        sys.exit(1)

    with open(sa_path) as f:
        sa = json.load(f)

    check("Has 'type' = 'service_account'", sa.get("type") == "service_account",
          f"Got: {sa.get('type', '(missing)')}")
    check("Has 'project_id'", bool(sa.get("project_id")),
          f"Project: {sa.get('project_id', '(missing)')}")
    check("Has 'client_email'", bool(sa.get("client_email")),
          f"Email: {sa.get('client_email', '(missing)')}")
    check("Has 'private_key'", bool(sa.get("private_key")),
          "Private key present" if sa.get("private_key") else "(missing)")

    # ── 2. Can create credentials ───────────────────────────────
    print(f"\n[2/6] Credential Loading")
    try:
        from google.oauth2 import service_account as sa_module
        SCOPES = [
            "https://www.googleapis.com/auth/documents",
            "https://www.googleapis.com/auth/gmail.compose",
        ]
        creds = sa_module.Credentials.from_service_account_file(sa_path, scopes=SCOPES)
        check("Credentials load successfully", True)
    except Exception as e:
        check("Credentials load successfully", False, str(e))
        all_passed = False

    # ── 3. Can get access token (proves key is valid) ───────────
    print(f"\n[3/6] Authentication (Token Request)")
    try:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
        check("Access token obtained", bool(creds.token),
              "Token is valid and not expired" if creds.valid else "Token invalid")
        if not creds.valid:
            all_passed = False
    except Exception as e:
        check("Access token obtained", False, str(e))
        all_passed = False

    # ── 4. Google Docs API enabled ──────────────────────────────
    print(f"\n[4/6] Google Docs API")
    try:
        from googleapiclient.discovery import build
        docs_service = build("docs", "v1", credentials=creds)
        # Try creating a minimal doc to test write access
        doc = docs_service.documents().create(body={"title": "__mcp_verification_test__"}).execute()
        doc_id = doc.get("documentId")
        check("Google Docs API is ENABLED", True, f"Test doc created: {doc_id}")
        
        # Try to clean up (delete via Drive API)
        try:
            drive_service = build("drive", "v3", credentials=creds)
            drive_service.files().delete(fileId=doc_id).execute()
            check("Cleanup: test doc deleted", True)
        except Exception:
            check("Cleanup: test doc deleted", False,
                  f"Manual cleanup needed. Delete doc: https://docs.google.com/document/d/{doc_id}")
    except Exception as e:
        err = str(e)
        if "has not been used" in err or "is not enabled" in err or "403" in err:
            check("Google Docs API is ENABLED", False,
                  "API is DISABLED. Enable it at: "
                  f"https://console.cloud.google.com/apis/library/docs.googleapis.com?project={sa.get('project_id')}")
        else:
            check("Google Docs API is ENABLED", False, err)
        all_passed = False

    # ── 5. Google Drive API (for doc cleanup/sharing) ───────────
    print(f"\n[5/5] Google Drive API")
    try:
        drive_service = build("drive", "v3", credentials=creds)
        about = drive_service.about().get(fields="user").execute()
        check("Google Drive API is ENABLED", True,
              f"Drive user: {about.get('user', {}).get('emailAddress', 'unknown')}")
    except Exception as e:
        err = str(e)
        if "has not been used" in err or "is not enabled" in err:
            check("Google Drive API is ENABLED", False,
                  "API is DISABLED. Enable it at: "
                  f"https://console.cloud.google.com/apis/library/drive.googleapis.com?project={sa.get('project_id')}")
        else:
            check("Google Drive API is ENABLED", False, err)
        all_passed = False

    # ── Final verdict ───────────────────────────────────────────
    print(f"\n{'='*60}")
    if all_passed:
        print("  🎉 ALL CHECKS PASSED — Your service account is ready!")
    else:
        print("  ⚠️  SOME CHECKS FAILED — See details above for fixes.")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
