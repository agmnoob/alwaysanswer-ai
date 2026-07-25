"""
AlwaysAnswer AI - Live Demo Outbound Agent
Calls prospects from landing page "Try It" button, qualifies, books calendar meeting.
"""

import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from dotenv import load_dotenv

load_dotenv()

from getpatter import Patter
from getpatter.carriers.twilio import Carrier as TwilioCarrier
from getpatter.stt.deepgram import STT as DeepgramSTT
from getpatter.tts.elevenlabs import TTS as ElevenLabsTTS
from getpatter.llm.anthropic import LLM as AnthropicLLM
from getpatter import guardrail, tool

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("demo-agent")

# =============================================================================
# DEMO AGENT SYSTEM PROMPT
# =============================================================================

DEMO_SYSTEM_PROMPT = """You are **Aria**, the AI sales specialist for **AlwaysAnswer AI** — white-label AI voice answering for local service businesses (HVAC, roofing, plumbing, salons).

## CONTEXT
The prospect just clicked "Try It" on our landing page and entered their phone number. They're a local service business owner/manager.

## YOUR GOAL
1. **Qualify** — Are they the decision maker? What trade? What CRM?
2. **Demo value** — Explain what the AI does for THEIR business (not generic)
3. **Book a 15-min calendar meeting** — Get them on your calendar
4. **Send SMS confirmation** — With meeting link

## CALL FLOW
1. **Greeting** (10 sec): Name, company, why you're calling
2. **Qualification** (30 sec): Decision maker? Trade? Current pain?
3. **Tailored pitch** (45 sec): Map AlwaysAnswer to their specific business
4. **Calendar booking** (30 sec): Offer 2-3 slots, book via tool
5. **SMS confirmation** (10 sec): Send meeting link
6. **Close** (5 sec): "You'll get a text with the link. Talk soon!"

## QUALIFICATION QUESTIONS (ask naturally)
- "Are you the owner or manager who handles phone systems?"
- "What trade — HVAC, roofing, plumbing, salon, something else?"
- "How are you handling after-hours calls right now?"
- "Do you use a CRM like ServiceTitan, Housecall Pro, Jobber, Mindbody?"
- "What's your biggest headache with calls — missed calls, no-shows, staffing?"

## VALUE MAPPING BY TRADE
| Trade | Pain Point | AlwaysAnswer Value |
|-------|------------|-------------------|
| HVAC | Summer emergency calls, dispatch chaos | Emergency dispatch logic, ServiceTitan sync, 24/7 no on-call staff |
| Roofing | Storm leads, insurance claims, seasonal | Lead capture + triage, CRM job creation, bilingual |
| Plumbing | Emergency leaks, after-hours, dispatch | Emergency routing, Housecall Pro sync, priority queue |
| Salon/Spa | No-shows, booking gaps, double-bookings | Mindbody/Booksy sync, automated reminders, waitlist |
| Electrician | Safety emergencies, permit questions | Emergency protocol, CRM integration, bilingual |

## GUARDRAILS
- NEVER quote exact price without discovery (say "starts at $297/mo per location")
- NEVER promise features not built (say "we can add that to the roadmap")
- If not decision maker: "Who should I send the info to? I'll email them too."
- If bad time: "When's a better time? I'll call back / text you the calendar link."

## TONE
Confident, consultative, not pushy. Sound like a specialist who knows their trade.
"""

# =============================================================================
# TOOL HANDLERS (replace with real integrations)
# =============================================================================

async def check_calendar_availability(
    preferred_date: str,
    preferred_time: str,
    duration_minutes: int = 15,
) -> Dict[str, Any]:
    """Check available demo meeting slots."""
    # TODO: Replace with Cal.com / Calendly / Google Calendar API
    available_slots = [
        {"date": "2026-07-22", "time": "10:00 AM", "timezone": "America/Los_Angeles"},
        {"date": "2026-07-22", "time": "2:00 PM", "timezone": "America/Los_Angeles"},
        {"date": "2026-07-23", "time": "9:00 AM", "timezone": "America/Los_Angeles"},
        {"date": "2026-07-23", "time": "1:00 PM", "timezone": "America/Los_Angeles"},
        {"date": "2026-07-24", "time": "11:00 AM", "timezone": "America/Los_Angeles"},
    ]
    
    preferred = next(
        (s for s in available_slots if s["date"] == preferred_date and s["time"] == preferred_time),
        None
    )
    
    return {
        "preferred_available": preferred is not None,
        "available_slots": available_slots[:3],
        "calendar_link": "https://calendar.app.google/YOUR_APPOINTMENT_PAGE",  # Google Appointment page (TODO: replace)
    }


async def book_calendar_meeting(
    prospect_name: str,
    prospect_phone: str,
    prospect_email: str,
    business_name: str,
    trade: str,
    crm: str,
    meeting_date: str,
    meeting_time: str,
    timezone: str = "America/Los_Angeles",
    duration_minutes: int = 15,
) -> Dict[str, Any]:
    """Book the demo meeting on calendar."""
    # TODO: Replace with Cal.com / Calendly / Google Calendar API
    logger.info(f"Booking meeting: {prospect_name} ({business_name}) on {meeting_date} at {meeting_time}")
    
    meeting_id = f"DEMO-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    
    return {
        "status": "booked",
        "meeting_id": meeting_id,
        "meeting_date": meeting_date,
        "meeting_time": meeting_time,
        "timezone": timezone,
        "duration_minutes": duration_minutes,
        "calendar_link": f"https://calendar.app.google/YOUR_APPOINTMENT_PAGE?meeting={meeting_id}",  # Google Appointment page (TODO: replace)
        "meet_link": f"https://meet.google.com/alwaysanswer-{meeting_id.lower()}",
        "message": f"Booked! {meeting_date} at {meeting_time} {timezone}. Calendar invite sent.",
    }


async def send_confirmation_sms(
    phone: str,
    meeting_date: str,
    meeting_time: str,
    meet_link: str,
    prospect_name: str = "there",
) -> Dict[str, Any]:
    """Send SMS confirmation with meeting link."""
    # TODO: Replace with Twilio SMS API
    message = (
        f"Hi {prospect_name}, thanks for the chat! "
        f"Your AlwaysAnswer AI demo is confirmed for {meeting_date} at {meeting_time}. "
        f"Join here: {meet_link} "
        f"– Aria from AlwaysAnswer AI"
    )
    logger.info(f"SMS to {phone}: {message}")
    return {"status": "sent", "message": message}


async def create_crm_lead(
    name: str,
    phone: str,
    email: str,
    business_name: str,
    trade: str,
    crm: str,
    locations: str,
    notes: str,
    source: str = "live_demo",
) -> Dict[str, Any]:
    """Create lead in CRM (HubSpot, Close, Pipedrive, etc.)."""
    # TODO: Replace with actual CRM webhook/API
    logger.info(f"Creating CRM lead: {name} - {business_name} ({trade})")
    return {
        "status": "created",
        "lead_id": f"LEAD-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "message": f"Lead created in CRM ({source})",
    }


async def lookup_prospect_by_phone(phone: str) -> Dict[str, Any]:
    """Check if we already have this prospect in our system."""
    # TODO: Replace with actual lookup
    return {"exists": False, "data": None}


# =============================================================================
# CALL LIFECYCLE HANDLERS
# =============================================================================

async def on_call_start(call_data: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich call with prospect data from landing page submission."""
    to_number = call_data.get("to", "Unknown")
    logger.info(f"Outbound demo call to: {to_number}")
    
    # TODO: Look up prospect data from landing page submission (via Redis/DB)
    # For now, return defaults that the agent can use
    return {
        "variables": {
            "prospect_name": "the business owner",
            "business_name": "your business",
            "trade": "your trade",
            "crm": "your current system",
        }
    }


async def on_call_end(call_data: Dict[str, Any]) -> None:
    """Log call outcome, update CRM, trigger follow-up."""
    duration = call_data.get("duration_seconds", 0)
    cost = call_data.get("cost_usd", 0)
    recording_url = call_data.get("recording_url")
    transcript = call_data.get("transcript")
    outcome = call_data.get("outcome", "unknown")
    
    logger.info(
        f"Demo call ended: {duration}s, ${cost:.4f}, outcome: {outcome}, "
        f"recording: {recording_url}"
    )
    
    # TODO: Update CRM with call outcome, trigger follow-up sequence


async def on_metrics(metrics: Dict[str, Any]) -> None:
    """Real-time call metrics."""
    call_id = metrics.get("call_id")
    cost = metrics.get("cost", {}).get("total", 0)
    latency = metrics.get("latency_p95", {}).get("total_ms", 0)
    logger.info(f"Demo call metrics: call={call_id} cost=${cost:.4f} p95_latency={latency}ms")


# =============================================================================
# AGENT FACTORY
# =============================================================================

def build_demo_agent():
    """Construct the outbound demo agent."""
    
    # LLM
    llm_provider = os.getenv("LLM_PROVIDER", "anthropic").lower()
    
    if llm_provider == "anthropic":
        llm = AnthropicLLM(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            model="claude-3-5-sonnet-20241022",
        )
    elif llm_provider == "openai":
        from getpatter.llm.openai import LLM as OpenAILLM
        llm = OpenAILLM(
            api_key=os.getenv("OPENAI_API_KEY"),
            model="gpt-4o-mini",
        )
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {llm_provider}")
    
    # STT
    stt = DeepgramSTT(
        api_key=os.getenv("DEEPGRAM_API_KEY"),
        model="nova-3",
        language="multi",
    )
    
    # TTS
    tts = ElevenLabsTTS(
        api_key=os.getenv("ELEVENLABS_API_KEY"),
        voice_id="21m00Tcm4TlvDq8ikWAM",  # Rachel - professional female
        model_id="eleven_flash_v2_5",
    )
    
    # Carrier
    carrier = TwilioCarrier(
        account_sid=os.getenv("TWILIO_ACCOUNT_SID"),
        auth_token=os.getenv("TWILIO_AUTH_TOKEN"),
    )
    
    # Patter instance
    phone = Patter(
        carrier=carrier,
        phone_number=os.getenv("TWILIO_PHONE_NUMBER"),
        webhook_url=os.getenv("WEBHOOK_URL"),
        mode="local" if not os.getenv("WEBHOOK_URL") else "production",
        pricing={
            "stt_per_minute": 0.0048,
            "tts_per_1k_chars": 0.05,
            "llm_input_per_1k_tokens": 0.003,
            "llm_output_per_1k_tokens": 0.015,
            "telephony_per_minute": 0.014,
        },
    )
    
    # Build agent
    agent = phone.agent(
        provider="pipeline",
        llm=llm,
        stt=stt,
        tts=tts,
        system_prompt=DEMO_SYSTEM_PROMPT,
        first_message=(
            "Hi, this is Aria from AlwaysAnswer AI. "
            "You just requested a demo on our site — I'm calling to give you "
            "a quick live walkthrough and book a 15-minute slot on the calendar. "
            "Is now a good time for 2 minutes?"
        ),
        language="en",
        variables={
            "prospect_name": "the business owner",
            "business_name": "your business",
            "trade": "your trade",
            "crm": "your current system",
        },
        guardrails=[
            guardrail(
                name="no_exact_price_without_discovery",
                check=lambda text: any(
                    term in text.lower()
                    for term in ["$297", "$399", "$497", "exactly $", "flat $"]
                ),
                replacement="Our plans start at $297/month per location. I'd need to understand your volume and CRM to give exact pricing — can we cover that on the 15-min call?",
            ),
            guardrail(
                name="no_false_promises",
                check=lambda text: any(
                    term in text.lower()
                    for term in ["guarantee", "100% accurate", "never miss", "perfect"]
                ),
                replacement="Our AI handles 95%+ of routine calls. For complex situations, it transfers to your team with full context. Want to see it work on the demo?",
            ),
            guardrail(
                name="stay_on_topic",
                check=lambda text: any(
                    term in text.lower()
                    for term in ["politics", "religion", "personal life", "unrelated"]
                ),
                replacement="Let's focus on your call handling. What's your biggest pain point with phones right now?",
            ),
        ],
        tools=[
            tool(
                name="check_calendar_availability",
                description="Check available demo meeting slots",
                parameters={
                    "type": "object",
                    "properties": {
                        "preferred_date": {"type": "string", "description": "YYYY-MM-DD"},
                        "preferred_time": {"type": "string", "description": "HH:MM AM/PM"},
                        "duration_minutes": {"type": "integer", "default": 15},
                    },
                    "required": ["preferred_date", "preferred_time"],
                },
                handler=check_calendar_availability,
            ),
            tool(
                name="book_calendar_meeting",
                description="Book the demo meeting on calendar",
                parameters={
                    "type": "object",
                    "properties": {
                        "prospect_name": {"type": "string"},
                        "prospect_phone": {"type": "string"},
                        "prospect_email": {"type": "string"},
                        "business_name": {"type": "string"},
                        "trade": {"type": "string"},
                        "crm": {"type": "string"},
                        "meeting_date": {"type": "string", "description": "YYYY-MM-DD"},
                        "meeting_time": {"type": "string", "description": "HH:MM AM/PM"},
                        "timezone": {"type": "string", "default": "America/Los_Angeles"},
                        "duration_minutes": {"type": "integer", "default": 15},
                    },
                    "required": [
                        "prospect_name", "prospect_phone", "prospect_email",
                        "business_name", "trade", "crm",
                        "meeting_date", "meeting_time"
                    ],
                },
                handler=book_calendar_meeting,
            ),
            tool(
                name="send_confirmation_sms",
                description="Send SMS with meeting confirmation link",
                parameters={
                    "type": "object",
                    "properties": {
                        "phone": {"type": "string"},
                        "meeting_date": {"type": "string"},
                        "meeting_time": {"type": "string"},
                        "meet_link": {"type": "string"},
                        "prospect_name": {"type": "string", "default": "there"},
                    },
                    "required": ["phone", "meeting_date", "meeting_time", "meet_link"],
                },
                handler=send_confirmation_sms,
            ),
            tool(
                name="create_crm_lead",
                description="Create lead in CRM with qualification data",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "phone": {"type": "string"},
                        "email": {"type": "string"},
                        "business_name": {"type": "string"},
                        "trade": {"type": "string"},
                        "crm": {"type": "string"},
                        "locations": {"type": "string"},
                        "notes": {"type": "string"},
                        "source": {"type": "string", "default": "live_demo"},
                    },
                    "required": ["name", "phone", "email", "business_name", "trade", "crm", "locations", "notes"],
                },
                handler=create_crm_lead,
            ),
        ],
    )
    
    return phone, agent


# =============================================================================
# OUTBOUND CALL TRIGGER (called by landing page API)
# =============================================================================

async def make_outbound_demo_call(
    phone_number: str,
    prospect_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Called by landing page API to trigger outbound demo call.
    """
    phone, agent = build_demo_agent()
    
    # Inject prospect data into agent variables
    agent.variables.update({
        "prospect_name": prospect_data.get("name", "the business owner"),
        "business_name": prospect_data.get("business_name", "your business"),
        "trade": prospect_data.get("trade", "your trade"),
        "crm": prospect_data.get("crm", "your current system"),
    })
    
    logger.info(f"Initiating outbound demo call to {phone_number}")
    
    # Make the call with answering machine detection
    result = await phone.call(
        to=phone_number,
        agent=agent,
        machine_detection=True,
        voicemail_message=(
            f"Hi {prospect_data.get('name', 'there')}, this is Aria from AlwaysAnswer AI. "
            f"You requested a demo on our site. I'll send you a text with a calendar link "
            f"to book a 15-minute walkthrough. Talk soon!"
        ),
    )
    
    return {
        "status": "initiated",
        "call_sid": getattr(result, "call_sid", None),
        "phone_number": phone_number,
    }


# =============================================================================
# MAIN - Run as server for local testing with tunnel
# =============================================================================

async def main():
    """Run the demo agent server (for local testing with tunnel)."""
    phone, agent = build_demo_agent()
    
    port = int(os.getenv("PORT", "8001"))
    dashboard_token = os.getenv("DASHBOARD_TOKEN", "demo-change-me")
    
    logger.info(f"Starting demo agent server on port {port}")
    logger.info(f"Dashboard: http://localhost:{port}/dashboard")
    
    await phone.serve(
        agent,
        port=port,
        recording=True,
        dashboard=True,
        dashboard_token=dashboard_token,
        on_call_start=on_call_start,
        on_call_end=on_call_end,
        on_metrics=on_metrics,
    )


if __name__ == "__main__":
    asyncio.run(main())