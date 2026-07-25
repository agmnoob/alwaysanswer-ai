"""
setup_calendar_auth.py — one-time Google Calendar OAuth for AlwaysAnswer AI.

Run:  python3 setup_calendar_auth.py
Opens a browser; you click through and grant access. token.json is saved
next to this script and reused by calendar_sync.py.

Prereqs:
  - Google Cloud project with the Calendar API enabled
  - OAuth2 "Desktop app" client credentials downloaded as credentials.json
    in this same folder.
"""

import os
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/calendar"]
HERE = os.path.dirname(os.path.abspath(__file__))
CRED_PATH = os.path.join(HERE, "credentials.json")
TOKEN_PATH = os.path.join(HERE, "token.json")


def main():
    if not os.path.exists(CRED_PATH):
        print(f"ERROR: credentials.json not found at {CRED_PATH}")
        print("Download OAuth2 Desktop client JSON from Google Cloud Console")
        print("and save it as credentials.json in this folder, then re-run.")
        return

    flow = InstalledAppFlow.from_client_secrets_file(CRED_PATH, SCOPES)
    creds = flow.run_local_server(port=0)  # opens browser, no manual copy
    with open(TOKEN_PATH, "w") as f:
        f.write(creds.to_json())
    print(f"OK — token saved to {TOKEN_PATH}")
    print("Calendar integration is now live.")


if __name__ == "__main__":
    main()
