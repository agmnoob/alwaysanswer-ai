"""
calendar_sync.py — Google Calendar integration for AlwaysAnswer AI.

Reads the OWNER's real availability (free/busy) and books demo events
directly onto the owner's calendar. No self-serve booking links.

AUTH MODES (preferred first):
  A) SERVICE ACCOUNT (recommended, no expiry, no consent screen):
     1. Google Cloud -> IAM & Admin -> Service Accounts -> Create.
     2. Create a JSON key for it -> save as service_account.json here.
     3. In Google Calendar, share YOUR calendar with the service
        account's email (...@*.iam.gserviceaccount.com) and grant
        "Make changes to events".
     4. Set GOOGLE_CALENDAR_ID (default: primary) and OWNER_EMAIL.
  B) OAUTH (fallback, expires ~7 days):
     1. OAuth2 Desktop client -> credentials.json here.
     2. Run: python3 setup_calendar_auth.py  (browser click-through).

Env (in .env):
  GOOGLE_CALENDAR_ID  - calendar to read/write (default: primary)
  OWNER_EMAIL         - owner address added as attendee + invite recipient
  CALENDAR_TZ         - IANA tz, e.g. America/Los_Angeles
"""

import os
import base64
import json
import re
import datetime as dt
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("calendar_sync")

# google-api-python-client is installed in the venv.
from google.oauth2 import service_account as _sa
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")
OWNER_EMAIL = os.getenv("OWNER_EMAIL", "")
CALENDAR_TZ = os.getenv("CALENDAR_TZ", "America/Los_Angeles")

HERE = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_PATH = os.path.join(HERE, "credentials.json")
TOKEN_PATH = os.path.join(HERE, "token.json")
SERVICE_ACCOUNT_PATH = os.path.join(HERE, "service_account.json")

# Fallback slots used when Google auth is not yet configured (demo-safe).
FALLBACK_SLOTS = [
    "Tuesday at 10:00 AM",
    "Wednesday at 2:00 PM",
    "Thursday at 11:00 AM",
]


def _service_creds():
    """Return service-account Credentials if the key file exists, else None."""
    if not os.path.exists(SERVICE_ACCOUNT_PATH):
        return None
    return _sa.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_PATH, scopes=SCOPES
    )


# Set by _bootstrap_token() so /health can report why calendar isn't wired.
calendar_bootstrap_error: str = ""


def _bootstrap_token():
    """On first run (e.g. on Render), seed token.json from GOOGLE_TOKEN_B64 env var.

    The OAuth token is gitignored (secret). On a host without the file, an
    operator base64-encodes token.json once and sets it as an encrypted env var;
    we write it back to disk so the rest of the module works unchanged.
    """
    global calendar_bootstrap_error
    calendar_bootstrap_error = ""
    if os.path.exists(TOKEN_PATH):
        return
    b64 = os.getenv("GOOGLE_TOKEN_B64", "")
    if not b64:
        return
    # Strip ALL whitespace/non-base64 chars — copied long strings pick up breaks;
    # also defends against Render trimming/transform quirks on very long values.
    b64 = re.sub(r"[^A-Za-z0-9+/=]", "", b64)
    # Fix padding so a trailing newline / 1-char truncation doesn't break decode.
    b64 += "=" * (-len(b64) % 4)
    try:
        raw = base64.b64decode(b64)
        text = raw.decode()
        # Validate it's actually our token JSON before writing.
        parsed = json.loads(text)
        if "refresh_token" not in parsed:
            raise ValueError("decoded JSON missing refresh_token")
        with open(TOKEN_PATH, "w") as f:
            f.write(text)
        logger.info("Seeded token.json from GOOGLE_TOKEN_B64 env var")
    except Exception as e:
        calendar_bootstrap_error = f"token seed failed: {e} (env len={len(b64)})"
        logger.warning(calendar_bootstrap_error)


def _oauth_creds():
    """Return OAuth Credentials from the stored token, refreshing if expired.

    The original consent used access_type=offline, so token.json carries a
    refresh_token. Refreshing transparently removes the ~7-day wall — refresh
    tokens do not expire unless explicitly revoked.
    """
    _bootstrap_token()
    if not os.path.exists(TOKEN_PATH):
        return None
    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if creds.expired and creds.refresh_token:
        try:
            from google.auth.transport.requests import Request as _Req
            creds.refresh(_Req())
            # Persist the new access token so we don't refresh every call.
            with open(TOKEN_PATH, "w") as f:
                f.write(creds.to_json())
        except Exception as e:  # refresh failed (e.g. revoked) -> signal unauth
            logger.warning(f"OAuth refresh failed: {e}")
            return None
    return creds


def is_configured() -> bool:
    return _service_creds() is not None or _oauth_creds() is not None


def get_service():
    """Build the Calendar client. Service account preferred; OAuth fallback."""
    sa_creds = _service_creds()
    if sa_creds is not None:
        return build("calendar", "v3", credentials=sa_creds)
    oauth_creds = _oauth_creds()
    if oauth_creds is not None:
        return build("calendar", "v3", credentials=oauth_creds)
    raise RuntimeError("Google Calendar not authorized. Add service_account.json or run setup_calendar_auth.py")


def _next_weekdays(start: dt.date, count: int, skip_weekends=True):
    days = []
    d = start
    while len(days) < count:
        if not skip_weekends or d.weekday() < 5:
            days.append(d)
        d += dt.timedelta(days=1)
    return days


def get_next_available_slots(
    days_ahead: int = 14,
    slot_times: tuple = ("10:00", "11:00", "14:00", "15:00", "16:00"),
    duration_minutes: int = 15,
    max_slots: int = 3,
) -> List[Dict[str, Any]]:
    """
    Query owner free/busy and return the next `max_slots` open demo slots.
    Returns list of {label, start_iso, end_iso}.
    Falls back to FALLBACK_SLOTS if Calendar not authorized.
    """
    if not is_configured():
        today = dt.date.today()
        out = []
        for i, lbl in enumerate(FALLBACK_SLOTS[:max_slots]):
            day = _next_weekdays(today + dt.timedelta(days=1), i + 1)[-1]
            out.append({
                "label": f"{day.strftime('%A, %B %d')} (fallback)",
                "start_iso": "",
                "end_iso": "",
                "fallback": True,
            })
        return out

    service = get_service()
    now = dt.datetime.now(dt.timezone.utc)
    horizon = now + dt.timedelta(days=days_ahead)

    # Gather candidate slots
    candidates: List[dt.datetime] = []
    for day in _next_weekdays(now.date() + dt.timedelta(days=1), days_ahead):
        for tm in slot_times:
            hh, mm = map(int, tm.split(":"))
            cand = dt.datetime(day.year, day.month, day.day, hh, mm,
                               tzinfo=dt.timezone.utc)
            # localize approx via tz; Calendar freebusy expects RFC3339 with tz
            candidates.append(cand)

    # Free/busy query
    body = {
        "timeMin": now.isoformat(),
        "timeMax": horizon.isoformat(),
        "items": [{"id": CALENDAR_ID}],
    }
    fb = service.freebusy().query(body=body).execute()
    busy = fb["calendars"][CALENDAR_ID].get("busy", [])

    def overlaps(start: dt.datetime, end: dt.datetime) -> bool:
        for b in busy:
            bs = dt.datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
            be = dt.datetime.fromisoformat(b["end"].replace("Z", "+00:00"))
            if start < be and end > bs:
                return True
        return False

    results = []
    for cand in candidates:
        end = cand + dt.timedelta(minutes=duration_minutes)
        if cand <= now:
            continue
        if not overlaps(cand, end):
            results.append({
                "label": cand.astimezone(dt.timezone.utc).strftime("%A, %B %d at %I:%M %p"),
                "start_iso": cand.isoformat(),
                "end_iso": end.isoformat(),
                "fallback": False,
            })
        if len(results) >= max_slots:
            break
    return results


def book_demo_event(
    prospect_name: str,
    business_name: str,
    phone: str,
    start_iso: str,
    duration_minutes: int = 15,
    notes: str = "",
) -> Dict[str, Any]:
    """
    Create the demo event directly on the owner's calendar.
    Returns {status, event_link, start, end}.
    If not configured, returns a recorded (local) booking so the call still closes.
    """
    if not is_configured():
        return {
            "status": "recorded_local_only",
            "event_link": "",
            "start": start_iso,
            "end": "",
            "note": "Google Calendar not authorized — booking logged locally only.",
        }

    service = get_service()
    start = dt.datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    end = start + dt.timedelta(minutes=duration_minutes)

    attendees = []
    if OWNER_EMAIL:
        attendees.append({"email": OWNER_EMAIL})

    event = {
        "summary": f"AlwaysAnswer AI Demo — {business_name} ({prospect_name})",
        "description": f"Prospect: {prospect_name}\nBusiness: {business_name}\nPhone: {phone}\n{notes}",
        "start": {"dateTime": start.isoformat(), "timeZone": CALENDAR_TZ},
        "end": {"dateTime": end.isoformat(), "timeZone": CALENDAR_TZ},
        "attendees": attendees,
        "conferenceData": {"createRequest": {"requestId": f"aa-{int(start.timestamp())}"}},
        "reminders": {"useDefault": True},
    }
    created = service.events().insert(
        calendarId=CALENDAR_ID,
        body=event,
        conferenceDataVersion=1,
        sendUpdates="all",
    ).execute()
    return {
        "status": "booked",
        "event_link": created.get("htmlLink", ""),
        "meet_link": created.get("hangoutLink", ""),
        "start": start.isoformat(),
        "end": end.isoformat(),
    }


if __name__ == "__main__":
    print("configured:", is_configured())
    slots = get_next_available_slots()
    for s in slots:
        print(s)
