"""
AlwaysAnswer AI - API Server for Landing Page Demo Calls
Handles outbound demo call triggers and Retell webhooks
"""

import os
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, EmailStr
from dotenv import load_dotenv

load_dotenv()

# Google Calendar integration (owner availability + direct booking)
try:
    import calendar_sync
except Exception as _cal_err:  # pragma: no cover - non-fatal if missing deps
    calendar_sync = None
    logging.getLogger("api-server").warning(f"calendar_sync unavailable: {_cal_err}")

# Stripe Checkout (server-side session creation; keys never touch the browser)
try:
    import stripe
except Exception as _stripe_err:
    stripe = None
    logging.getLogger("api-server").warning(f"stripe unavailable: {_stripe_err}")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("api-server")

# =============================================================================
# CONFIGURATION
# =============================================================================

RETELL_API_KEY = os.getenv("RETELL_API_KEY", "key_a2bc4c162c9b896515c2733dab2d")
DEMO_AGENT_ID = os.getenv("DEMO_AGENT_ID", "agent_bca52ead31040cd2b6b8f7b6c7")  # Aria demo agent
# Public base URL for Retell webhooks / Stripe callbacks.
# Prefer explicit WEBHOOK_BASE_URL; fall back to Render's injected external URL;
# then localhost for local dev. This means on Render the var is auto-set.
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL") or os.getenv(
    "RENDER_EXTERNAL_URL", "http://localhost:8080"
)

# Booking link Aria sends prospects. Default = Google Calendar appointment-schedule page
# (Google's free built-in Cal.com equivalent). Create one at calendar.google.com -> "Appointments"
# and paste the share URL here. Falls back to Cal.com if you prefer that.
BOOKING_LINK = os.getenv(
    "BOOKING_LINK",
    "https://calendar.app.google/YOUR_APPOINTMENT_PAGE",  # TODO: replace with your real Google Appointment link
)

# --- Stripe Checkout ---
# Create prices in Stripe Dashboard (Test mode first), paste the Price IDs below.
# Secret key stays server-side only. Publishable key is safe in the browser but
# we don't even need it here because we redirect via a server-created Session.
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_IDS = {
    "starter": os.getenv("STRIPE_PRICE_STARTER", ""),  # $197/mo
    "growth": os.getenv("STRIPE_PRICE_GROWTH", ""),    # $497/mo limited
    # pro => custom, no fixed price -> contact form only
}
STRIPE_SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL", f"{WEBHOOK_BASE_URL}/success?session_id={{CHECKOUT_SESSION_ID}}")
STRIPE_CANCEL_URL = os.getenv("STRIPE_CANCEL_URL", f"{WEBHOOK_BASE_URL}/#pricing")

if stripe and STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# In-memory store for demo calls (replace with Redis/DB in production)
demo_calls: Dict[str, Dict[str, Any]] = {}

# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class DemoCallRequest(BaseModel):
    """Request to trigger a live demo outbound call"""
    name: str = Field(..., min_length=1, max_length=100)
    business_name: str = Field(..., min_length=1, max_length=100)
    phone: str = Field(..., min_length=10, max_length=20)
    email: EmailStr = Field(default="")
    trade: str = Field(default="hvac")
    crm: str = Field(default="none")
    locations: str = Field(default="1")
    notes: str = Field(default="")

class DemoCallResponse(BaseModel):
    """Response from demo call trigger"""
    status: str  # "initiated", "queued", "error"
    message: str
    call_id: Optional[str] = None
    estimated_callback_seconds: int = 15

class LeadCaptureRequest(BaseModel):
    """Lead capture from contact form"""
    name: str = Field(..., min_length=1, max_length=100)
    biz: str = Field(..., min_length=1, max_length=100)
    phone: str = Field(..., min_length=10, max_length=20)
    email: EmailStr = Field(default="")
    trade: str = Field(default="")
    crm: str = Field(default="")
    locs: str = Field(default="1")
    msg: str = Field(default="")

class LeadCaptureResponse(BaseModel):
    status: str
    message: str
    calendar_link: str = BOOKING_LINK

class CheckoutRequest(BaseModel):
    """Create a Stripe Checkout Session for a paid plan (starter / growth)."""
    plan: str = Field(..., description="'starter' or 'growth'")

class CheckoutResponse(BaseModel):
    status: str
    url: str = ""

class BookAppointmentToolRequest(BaseModel):
    """Called by Aria's book_appointment custom tool during a live demo call."""
    prospect_name: str = Field(..., min_length=1, max_length=120)
    business_name: str = Field(..., min_length=1, max_length=120)
    phone: str = Field(..., min_length=10, max_length=20)
    datetime_slot: str = Field(..., description="Human-spoken slot as offered, e.g. 'Tuesday July 28 at 10 AM'")
    start_iso: Optional[str] = Field(default=None, description="Exact ISO start from check_availability (preferred for booking)")

class CheckAvailabilityToolRequest(BaseModel):
    """Called by Aria's check_availability tool to pull the owner's next open demo slots."""
    max_slots: int = Field(default=3, ge=1, le=5)
    days_ahead: int = Field(default=14, ge=1, le=60)

class SendCallbackToolRequest(BaseModel):
    """Called by Aria's send_callback custom tool when prospect refuses to book."""
    prospect_name: str = Field(..., min_length=1, max_length=120)
    business_name: str = Field(..., min_length=1, max_length=120)
    phone: str = Field(..., min_length=10, max_length=20)
    notes: str = Field(default="")

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def normalize_phone(phone: str) -> str:
    """Normalize phone to E.164 format"""
    import re
    digits = re.sub(r'\D', '', phone)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits[0] == "1":
        return f"+{digits}"
    if digits.startswith("1") and len(digits) > 10:
        return f"+{digits}"
    return f"+{digits}"

def validate_phone_e164(phone: str) -> bool:
    """Basic E.164 validation"""
    import re
    return bool(re.match(r'^\+[1-9]\d{9,14}$', phone))

# Simple in-memory rate limiting
call_log: Dict[str, list] = {}

def check_rate_limit(ip: str, max_calls_per_hour: int = 5) -> bool:
    """Simple in-memory rate limiting"""
    now = datetime.now().timestamp()
    hour_ago = now - 3600
    
    if ip not in call_log:
        call_log[ip] = []
    
    call_log[ip] = [ts for ts in call_log[ip] if ts > hour_ago]
    
    if len(call_log[ip]) >= max_calls_per_hour:
        return False
    
    call_log[ip].append(now)
    return True

# =============================================================================
# RETELL API INTEGRATION
# =============================================================================

async def create_retell_phone_call(
    to_number: str,
    agent_id: str,
    retell_llm_id: str = "llm_3b400944649844442361e4f7fce2",
    prospect_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Create an outbound phone call via Retell API"""
    import httpx
    
    # Prepare dynamic variables for the agent
    dynamic_variables = {}
    if prospect_data:
        dynamic_variables = {
            "prospect_name": prospect_data.get("name", "the business owner"),
            "business_name": prospect_data.get("business_name", "your business"),
            "trade": prospect_data.get("trade", "your trade"),
            "crm": prospect_data.get("crm", "your current system"),
        }
    
    payload = {
        "to_number": to_number,
        "agent_id": agent_id,
        "retell_llm_dynamic_variables": dynamic_variables,
        "machine_detection": True,
        "voicemail_message": (
            f"Hi {prospect_data.get('name', 'there')}, this is Aria from AlwaysAnswer AI. "
            f"You requested a demo on our website. I'll send you a text with a calendar link "
            f"to book a 15-minute walkthrough. Talk soon!"
        ),
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.retellai.com/create-phone-call",
            headers={
                "Authorization": f"Bearer {RETELL_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        
        if response.status_code >= 400:
            logger.error(f"Retell API error: {response.status_code} - {response.text}")
            raise HTTPException(status_code=500, detail=f"Retell API error: {response.text}")
        
        return response.json()

# =============================================================================
# FASTAPI APP
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting AlwaysAnswer AI API server...")
    logger.info(f"Retell API key configured: {bool(RETELL_API_KEY)}")
    logger.info(f"Demo Agent ID: {DEMO_AGENT_ID or 'Not set'}")
    yield
    logger.info("Shutting down API server...")

app = FastAPI(
    title="AlwaysAnswer AI API",
    description="Backend for landing page demo calls and lead capture",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# ROUTES
# =============================================================================

@app.get("/health")
async def health_check():
    cal_ok = False
    if calendar_sync is not None:
        try:
            cal_ok = calendar_sync.is_configured()
        except Exception:
            cal_ok = False
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "version": "1.0.0",
        "retell_configured": bool(RETELL_API_KEY),
        "demo_agent_id": DEMO_AGENT_ID or "not_set",
        "calendar_configured": cal_ok,
        "webhook_base_url": WEBHOOK_BASE_URL or "",
    }

@app.post("/api/demo-call", response_model=DemoCallResponse)
async def trigger_demo_call(
    request: DemoCallRequest,
    background_tasks: BackgroundTasks,
    request_obj: Request,
):
    """
    Trigger an outbound demo call from the landing page.
    This is called when a prospect clicks "Call me now" on the landing page.
    """
    client_ip = request_obj.client.host if request_obj.client else "unknown"
    
    # Rate limiting
    if not check_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Too many demo requests. Please wait an hour or contact us directly."
        )
    
    # Validate phone
    normalized_phone = normalize_phone(request.phone)
    if not validate_phone_e164(normalized_phone):
        raise HTTPException(
            status_code=400,
            detail="Invalid phone number format. Use E.164 format (e.g., +13105551234)"
        )
    
    if not DEMO_AGENT_ID:
        raise HTTPException(
            status_code=503,
            detail="Demo agent not configured. Please contact support."
        )
    
    # Prepare prospect data for the agent
    prospect_data = {
        "name": request.name.strip(),
        "business_name": request.business_name.strip(),
        "trade": request.trade.lower(),
        "crm": request.crm.lower(),
        "locations": request.locations,
        "notes": request.notes.strip(),
    }
    
    logger.info(f"Demo call requested for {normalized_phone} ({request.name}, {request.business_name})")
    
    # Trigger the call in background
    async def make_call():
        try:
            result = await create_retell_phone_call(
                to_number=normalized_phone,
                agent_id=DEMO_AGENT_ID,
                prospect_data=prospect_data,
            )
            call_id = result.get("call_id") or result.get("call_sid") or "unknown"
            demo_calls[call_id] = {
                "call_id": call_id,
                "phone": normalized_phone,
                "prospect": prospect_data,
                "status": "initiated",
                "created_at": datetime.utcnow().isoformat(),
                "retell_result": result,
            }
            logger.info(f"Demo call initiated: {call_id} -> {normalized_phone}")
        except Exception as e:
            logger.error(f"Failed to initiate demo call: {e}")
            demo_calls[f"failed_{datetime.utcnow().timestamp()}"] = {
                "phone": normalized_phone,
                "prospect": prospect_data,
                "status": "failed",
                "error": str(e),
                "created_at": datetime.utcnow().isoformat(),
            }
    
    background_tasks.add_task(make_call)
    
    return DemoCallResponse(
        status="queued",
        message="Demo call queued! Your phone will ring within 15 seconds. Answer and talk to Aria!",
        estimated_callback_seconds=15,
    )

# In-memory store for tool-originated demo bookings / callbacks
tool_leads: Dict[str, Dict[str, Any]] = {}

@app.post("/api/check-availability")
async def tool_check_availability(request: CheckAvailabilityToolRequest, request_obj: Request):
    """
    Called by Aria's check_availability custom tool.
    Returns the OWNER's next open demo slots (read from Google Calendar free/busy),
    so Aria can offer the next soonest time and keep the lead warm on the call.
    """
    if calendar_sync is None:
        return {"status": "unavailable", "slots": [], "message": "Calendar not configured."}
    try:
        slots = calendar_sync.get_next_available_slots(
            days_ahead=request.days_ahead, max_slots=request.max_slots
        )
        return {
            "status": "ok",
            "configured": calendar_sync.is_configured(),
            "slots": slots,
            "message": "Here are the owner's next available demo times.",
        }
    except Exception as e:
        logger.error(f"check_availability failed: {e}")
        return {"status": "error", "slots": [], "message": str(e)}

@app.post("/api/book-appointment")
async def tool_book_appointment(request: BookAppointmentToolRequest, request_obj: Request):
    """
    Called by Aria's book_appointment custom tool during a live demo call.
    Books the demo directly onto the OWNER's Google Calendar (no self-serve link).
    """
    normalized_phone = normalize_phone(request.phone)
    entry = {
        "type": "booked_demo",
        "prospect_name": request.prospect_name.strip(),
        "business_name": request.business_name.strip(),
        "phone": normalized_phone,
        "datetime_slot": request.datetime_slot.strip(),
        "created_at": datetime.utcnow().isoformat(),
    }

    if calendar_sync is not None:
        try:
            result = calendar_sync.book_demo_event(
                prospect_name=request.prospect_name.strip(),
                business_name=request.business_name.strip(),
                phone=normalized_phone,
                start_iso=request.start_iso or "",
                notes=f"Offered slot: {request.datetime_slot}",
            )
            entry.update(result)
            entry["status"] = result.get("status", "booked")
            resp_msg = (
                f"Perfect — you're booked for {request.datetime_slot}. "
                f"I've put it on the calendar and sent you an invite."
            )
        except Exception as e:
            logger.error(f"book_demo_event failed: {e}")
            entry["status"] = "recorded_local_only"
            entry["error"] = str(e)
            resp_msg = f"Booked for {request.datetime_slot}. We'll confirm by text shortly."
    else:
        entry["status"] = "recorded_local_only"
        resp_msg = f"Booked for {request.datetime_slot}. We'll confirm by text shortly."

    tool_leads[f"book_{datetime.utcnow().timestamp()}"] = entry
    logger.info(f"BOOKED via tool: {request.prospect_name} ({request.business_name}) @ {request.datetime_slot}")

    return {
        "status": entry["status"],
        "event_link": entry.get("event_link", ""),
        "meet_link": entry.get("meet_link", ""),
        "message": resp_msg,
    }

@app.post("/api/send-callback")
async def tool_send_callback(request: SendCallbackToolRequest, request_obj: Request):
    """
    Called by Aria's send_callback custom tool when the prospect refuses a fixed slot
    and asks to be called back instead. Queues a manual callback task.
    """
    normalized_phone = normalize_phone(request.phone)
    entry = {
        "type": "callback_request",
        "prospect_name": request.prospect_name.strip(),
        "business_name": request.business_name.strip(),
        "phone": normalized_phone,
        "notes": request.notes.strip(),
        "created_at": datetime.utcnow().isoformat(),
    }
    tool_leads[f"cb_{datetime.utcnow().timestamp()}"] = entry
    logger.info(f"CALLBACK requested via tool: {request.prospect_name} ({request.business_name})")

    # TODO: route to a live rep queue / CRM task
    return {
        "status": "callback_queued",
        "message": f"Got it, {request.prospect_name}. I've flagged {request.business_name} for a "
                   f"personal callback from our team. We'll reach out shortly.",
    }

@app.post("/api/checkout", response_model=CheckoutResponse)
async def create_checkout(request: CheckoutRequest, request_obj: Request):
    """
    Create a Stripe Checkout Session for a paid plan and return the redirect URL.
    Secret key stays server-side. Prospect is sent to Stripe's hosted pay page.
    """
    plan = request.plan.lower()
    if plan not in STRIPE_PRICE_IDS or plan == "pro":
        raise HTTPException(status_code=400, detail="Invalid or unsupported plan")
    price_id = STRIPE_PRICE_IDS.get(plan)
    if stripe is None or not STRIPE_SECRET_KEY or not price_id:
        # Not configured — degrade gracefully so the page never dead-ends.
        return CheckoutResponse(status="unavailable")

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=STRIPE_SUCCESS_URL,
            cancel_url=STRIPE_CANCEL_URL,
            allow_promotion_codes=True,
            client_reference_id=plan,
        )
        return CheckoutResponse(status="ok", url=session.url)
    except Exception as e:
        logger.error(f"Stripe checkout failed: {e}")
        raise HTTPException(status_code=502, detail="Checkout creation failed")


@app.get("/success")
async def checkout_success(session_id: str = ""):
    """Simple post-payment confirmation page."""
    return HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Welcome to AlwaysAnswer AI</title>"
        "<style>body{font-family:system-ui,sans-serif;background:#0a0a0a;color:#fff;"
        "display:flex;min-height:100vh;align-items:center;justify-content:center;text-align:center}"
        "h1{font-size:32px} p{color:#aaa;max-width:440px}</style></head>"
        "<body><div><h1>You're all set 🎉</h1>"
        "<p>Thanks for subscribing to AlwaysAnswer AI. Our team will reach out within one "
        "business day to get your location live. Questions? Reply to your confirmation email.</p>"
        "</div></body></html>"
    )


@app.post("/api/lead", response_model=LeadCaptureResponse)
async def capture_lead(request: LeadCaptureRequest, request_obj: Request):
    """
    Capture a lead from the contact form without triggering a call.
    For prospects who prefer to book their own time.
    """
    client_ip = request_obj.client.host if request_obj.client else "unknown"
    
    if not check_rate_limit(client_ip, max_calls_per_hour=10):
        raise HTTPException(status_code=429, detail="Rate limited")
    
    normalized_phone = normalize_phone(request.phone)
    if not validate_phone_e164(normalized_phone):
        raise HTTPException(status_code=400, detail="Invalid phone format")
    
    logger.info(f"Lead captured: {request.name} - {request.biz} - {normalized_phone}")
    
    # TODO: Send to CRM, trigger email sequence, etc.
    
    return LeadCaptureResponse(
        status="captured",
        message="Thanks! We'll reach out within one business day to schedule your demo.",
        calendar_link=BOOKING_LINK,
    )

@app.post("/webhook/retell")
async def retell_webhook(request: Request):
    """
    Retell webhook endpoint for call events.
    Handles: call_started, call_ended, call_analyzed, etc.
    """
    body = await request.json()
    event = body.get("event", "unknown")
    call_id = body.get("call_id", "unknown")
    
    logger.info(f"Retell webhook: {event} for call {call_id}")
    
    if event == "call_started":
        if call_id in demo_calls:
            demo_calls[call_id]["status"] = "in_progress"
            demo_calls[call_id]["started_at"] = datetime.utcnow().isoformat()
    
    elif event == "call_ended":
        if call_id in demo_calls:
            demo_calls[call_id]["status"] = "completed"
            demo_calls[call_id]["ended_at"] = datetime.utcnow().isoformat()
            demo_calls[call_id]["duration_seconds"] = body.get("duration_seconds")
            demo_calls[call_id]["cost_usd"] = body.get("cost_usd")
            demo_calls[call_id]["recording_url"] = body.get("recording_url")
            demo_calls[call_id]["transcript"] = body.get("transcript")
    
    elif event == "call_analyzed":
        if call_id in demo_calls:
            demo_calls[call_id]["analysis"] = body.get("analysis", {})
    
    return {"status": "ok"}

@app.get("/api/demo-calls")
async def list_demo_calls():
    """List recent demo calls (for debugging/monitoring)"""
    return {
        "calls": list(demo_calls.values())[-20:],
        "total": len(demo_calls),
    }

# Serve the landing page from this same service so the page + API share one origin.
# Mounted LAST so explicit /api/* and /health routes win route matching.
LANDING_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "landing")
if os.path.isdir(LANDING_DIR):
    app.mount("/", StaticFiles(directory=LANDING_DIR, html=True), name="landing")

# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("API_PORT", "8080"))
    uvicorn.run("api_server:app", host="0.0.0.0", port=port, reload=True, log_level="info")