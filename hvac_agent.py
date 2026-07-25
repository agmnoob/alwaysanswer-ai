"""
AlwaysAnswer AI - HVAC Inbound Agent
Production-ready voice agent for HVAC businesses.
Handles: after-hours emergency dispatch, appointment booking, general inquiries.
"""

import os
import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from dotenv import load_dotenv

from getpatter import Patter, guardrail, tool
from getpatter.carriers.twilio import Carrier as TwilioCarrier
from getpatter.stt.deepgram import STT as DeepgramSTT
from getpatter.tts.elevenlabs import TTS as ElevenLabsTTS
from getpatter.llm.openai import LLM as OpenAILLM
from getpatter.llm.anthropic import LLM as AnthropicLLM
from getpatter.engines.openai import Realtime as OpenAIRealtime

# Load environment
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("hvac-agent")

# =============================================================================
# HVAC-SPECIFIC SYSTEM PROMPT
# =============================================================================

HVAC_SYSTEM_PROMPT = """You are **Alex**, the AI voice receptionist for **{business_name}**, a professional HVAC company serving the {service_area} area.

## YOUR ROLE
Answer inbound calls 24/7/365. Handle three call types:
1. **EMERGENCY** (no heat/AC, gas smell, water leak, electrical issue) → Dispatch immediately
2. **APPOINTMENT REQUEST** (maintenance, repair quote, new install) → Book in CRM
3. **GENERAL INQUIRY** (pricing, hours, services, warranty) → Answer from knowledge base

## CALL FLOW
1. Greet with company name and your name (Alex)
2. Identify call type within 30 seconds using qualifying questions
3. Execute appropriate workflow
4. Confirm details back to caller
5. Close professionally

## EMERGENCY PROTOCOL (HIGHEST PRIORITY)
If caller mentions ANY of these keywords, treat as EMERGENCY:
- "no heat" / "no AC" / "not cooling" / "not heating" / "broken"
- "gas smell" / "gas leak" / "rotten eggs" / "carbon monoxide"
- "water leaking" / "water damage" / "flooding" / "pipe burst"
- "electrical" / "sparking" / "burning smell" / "smoke"
- "emergency" / "urgent" / "right now" / "immediately"

Emergency response:
- "This sounds urgent. I'm dispatching our on-call technician now."
- Collect: address, best contact number, issue details, access instructions
- Confirm: "Tech [Name] will call you within 15 minutes. They have your address: [address]. Is there a gate code or special access?"
- Set expectation: "Our emergency service fee is $149 dispatch + parts/labor. Do you approve?"

## APPOINTMENT BOOKING
Required fields for booking:
- Customer name, phone, email
- Service address (verify zip code in service area)
- Preferred date/time (offer 2-3 slots)
- System type (furnace, AC, heat pump, mini-split, boiler)
- Issue description
- New vs existing customer

Confirm: "I've booked [Date] at [Time] for [Service]. Our tech will call 30 min before arrival. You'll get a text confirmation. Anything else?"

## KNOWLEDGE BASE (answer without booking)
- **Hours**: Mon-Fri 7am-7pm, Sat 8am-4pm, Sun closed (24/7 emergency)
- **Service area**: {service_area} + 15-mile radius
- **Brands**: Carrier, Trane, Lennox, Mitsubishi, Daikin, Rheem, Goodman
- **Maintenance plan**: $199/yr = 2 tune-ups + 10% repairs + priority scheduling
- **Emergency fee**: $149 dispatch + parts/labor (waived with maintenance plan)
- **Financing**: 0% for 12 months on installs >$5k
- **Warranty**: 10-year parts on new installs, 1-year labor

## GUARDRAILS
- NEVER give medical, legal, or electrical code advice
- NEVER quote exact repair price without inspection (say "starts at $X")
- NEVER promise specific technician by name unless dispatched
- If caller asks for human: "I can transfer you to our office during business hours, or our on-call manager after hours. Which do you prefer?"
- If out of service area: "We serve [area]. For your location, I recommend [partner]."

## TONE
Professional, warm, efficient. Use caller's name. Mirror urgency on emergencies.
"""

# =============================================================================
# TOOL HANDLERS (replace with actual CRM/webhook integrations)
# =============================================================================

async def dispatch_emergency(
    address: str,
    issue: str,
    contact_name: str,
    contact_phone: str,
    access_notes: str = "",
    gate_code: str = "",
) -> Dict[str, Any]:
    """Dispatch on-call technician for emergency."""
    logger.info(f"EMERGENCY DISPATCH: {contact_name} at {address} - {issue}")
    return {
        "status": "dispatched",
        "tech_name": "Mike (on-call)",
        "eta_minutes": 15,
        "dispatch_id": f"EMG-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "message": f"Tech Mike dispatched. Will call {contact_phone} within 15 min. ETA to {address}: ~30 min."
    }


async def book_appointment(
    customer_name: str,
    phone: str,
    email: str,
    address: str,
    city: str,
    state: str,
    zip_code: str,
    preferred_date: str,
    preferred_time: str,
    service_type: str,  # maintenance, repair, install_quote
    system_type: str,   # furnace, ac, heat_pump, mini_split, boiler, other
    issue_description: str,
    is_existing_customer: bool = False,
) -> Dict[str, Any]:
    """Book appointment in CRM (ServiceTitan / Housecall Pro / Jobber)."""
    logger.info(f"BOOKING: {customer_name} - {preferred_date} {preferred_time} - {service_type}")
    return {
        "status": "booked",
        "appointment_id": f"APT-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "confirmed_date": preferred_date,
        "confirmed_time": preferred_time,
        "tech_assigned": "TBD (assigned morning of)",
        "confirmation_text": True,
        "message": f"Booked {service_type} for {preferred_date} at {preferred_time}. Confirmation text sent to {phone}."
    }


async def check_maintenance_plan(customer_phone: str) -> Dict[str, Any]:
    """Check if customer has active maintenance plan."""
    return {
        "has_plan": False,
        "plan_name": None,
        "expires": None,
    }


async def send_confirmation_sms(phone: str, message: str) -> Dict[str, Any]:
    """Send SMS confirmation via Twilio."""
    logger.info(f"SMS to {phone}: {message}")
    return {"status": "sent"}


# =============================================================================
# CALL LIFECYCLE HANDLERS
# =============================================================================

async def on_call_start(call_data: Dict[str, Any]) -> Dict[str, Any]:
    """Called when inbound call starts. Lookup customer, enrich with CRM data."""
    caller_id = call_data.get("from", "Unknown")
    logger.info(f"Inbound call from: {caller_id}")
    
    # TODO: Look up customer by phone in CRM
    customer = await lookup_customer_by_phone(caller_id)
    
    variables = {
        "business_name": os.getenv("BUSINESS_NAME", "Comfort HVAC"),
        "service_area": os.getenv("SERVICE_AREA", "Greater Los Angeles"),
        "customer_name": customer.get("name", "Valued Customer"),
        "is_existing_customer": str(customer.get("exists", False)).lower(),
        "has_maintenance_plan": str(customer.get("has_plan", False)).lower(),
    }
    
    return {"variables": variables}


async def on_call_end(call_data: Dict[str, Any]) -> None:
    """Called when call ends. Log, record, create CRM activity."""
    duration = call_data.get("duration_seconds", 0)
    cost = call_data.get("cost_usd", 0)
    recording_url = call_data.get("recording_url")
    transcript = call_data.get("transcript")
    
    logger.info(f"Call ended: {duration}s, ${cost:.4f}, recording: {recording_url}")
    
    # TODO: Create CRM activity, save recording/transcript, update analytics


async def on_metrics(metrics: Dict[str, Any]) -> None:
    """Real-time metrics callback."""
    call_id = metrics.get("call_id")
    cost = metrics.get("cost", {}).get("total", 0)
    latency = metrics.get("latency_p95", {}).get("total_ms", 0)
    logger.info(f"Metrics: call={call_id} cost=${cost:.4f} p95_latency={latency}ms")


async def lookup_customer_by_phone(phone: str) -> Dict[str, Any]:
    """Look up customer in CRM by phone number."""
    # TODO: Implement actual CRM lookup (ServiceTitan, Housecall, HubSpot, etc.)
    return {
        "exists": False,
        "name": "Valued Customer",
        "has_plan": False,
    }


# =============================================================================
# AGENT FACTORY
# =============================================================================

def build_agent() -> tuple[Patter, Any]:
    """Construct the HVAC agent with all providers and tools."""
    
    # Determine LLM provider from env
    llm_provider = os.getenv("LLM_PROVIDER", "anthropic").lower()
    
    if llm_provider == "anthropic":
        llm = AnthropicLLM(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            model="claude-3-5-sonnet-20241022",
        )
    elif llm_provider == "openai":
        llm = OpenAILLM(
            api_key=os.getenv("OPENAI_API_KEY"),
            model="gpt-4o-mini",
        )
    elif llm_provider == "openrouter":
        llm = OpenAILLM(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api/v1",
            model="anthropic/claude-3.5-sonnet",
        )
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {llm_provider}")
    
    # STT - Deepgram Nova-3
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
    
    # Telephony - Twilio
    carrier = TwilioCarrier(
        account_sid=os.getenv("TWILIO_ACCOUNT_SID"),
        auth_token=os.getenv("TWILIO_AUTH_TOKEN"),
    )
    
    # Build Patter instance
    phone = Patter(
        carrier=carrier,
        phone_number=os.getenv("TWILIO_PHONE_NUMBER"),
        webhook_url=os.getenv("WEBHOOK_URL"),
        mode="local" if not os.getenv("WEBHOOK_URL") else "production",
        pricing={
            "stt_per_minute": 0.0048,       # Deepgram Nova-3 promo
            "tts_per_1k_chars": 0.05,        # ElevenLabs Flash v2.5
            "llm_input_per_1k_tokens": 0.003,
            "llm_output_per_1k_tokens": 0.015,
            "telephony_per_minute": 0.014,   # Twilio
        },
    )
    
    # Business context for prompt
    business_name = os.getenv("BUSINESS_NAME", "Comfort HVAC")
    service_area = os.getenv("SERVICE_AREA", "Greater Los Angeles")
    
    system_prompt = HVAC_SYSTEM_PROMPT.format(
        business_name=business_name,
        service_area=service_area,
    )
    
    # Create agent with tools and guardrails
    agent = phone.agent(
        provider="pipeline",  # STT -> LLM -> TTS (not realtime)
        llm=llm,
        stt=stt,
        tts=tts,
        system_prompt=system_prompt,
        first_message="Hello, thank you for calling {business_name}. This is Alex. How can I help you today?",
        language="en",
        variables={
            "business_name": business_name,
            "service_area": service_area,
            "customer_name": "Valued Customer",
            "is_existing_customer": "false",
            "has_maintenance_plan": "false",
        },
        guardrails=[
            guardrail(
                name="no_competitor_mentions",
                blocked_terms=["competitor", "rival company", "switch providers", "cancel service"],
                replacement="I'd love to focus on how {business_name} can help you. What do you need?",
            ),
            guardrail(
                name="no_medical_legal_advice",
                check=lambda text: any(
                    term in text.lower()
                    for term in ["diagnosis", "prescription", "legal advice", "lawsuit", "code violation"]
                ),
                replacement="I'm not qualified to advise on that. Let me transfer you to a specialist or our manager.",
            ),
            guardrail(
                name="emergency_keyword_trigger",
                check=lambda text: any(
                    term in text.lower()
                    for term in ["gas leak", "carbon monoxide", "electrical fire", "sparking wires"]
                ),
                replacement="This is a safety emergency. I'm dispatching help immediately. Please evacuate if safe to do so.",
            ),
        ],
        tools=[
            tool(
                name="dispatch_emergency",
                description="Dispatch on-call technician for emergency (no heat/AC, gas leak, water leak, electrical)",
                parameters={
                    "type": "object",
                    "properties": {
                        "address": {"type": "string", "description": "Full service address"},
                        "issue": {"type": "string", "description": "Emergency details: no heat, gas smell, water leak, etc."},
                        "contact_name": {"type": "string", "description": "Customer's name"},
                        "contact_phone": {"type": "string", "description": "Best callback number"},
                        "access_notes": {"type": "string", "description": "Gate code, lockbox, pet info, etc."},
                        "gate_code": {"type": "string", "description": "Gate/entry code if applicable"},
                    },
                    "required": ["address", "issue", "contact_name", "contact_phone"],
                },
                handler=dispatch_emergency,
            ),
            tool(
                name="book_appointment",
                description="Book HVAC service appointment (maintenance, repair, install quote)",
                parameters={
                    "type": "object",
                    "properties": {
                        "customer_name": {"type": "string"},
                        "phone": {"type": "string"},
                        "email": {"type": "string"},
                        "address": {"type": "string"},
                        "city": {"type": "string"},
                        "state": {"type": "string"},
                        "zip_code": {"type": "string"},
                        "preferred_date": {"type": "string", "description": "YYYY-MM-DD"},
                        "preferred_time": {"type": "string", "description": "HH:MM AM/PM"},
                        "service_type": {"type": "string", "enum": ["maintenance", "repair", "install_quote"]},
                        "system_type": {"type": "string", "enum": ["furnace", "ac", "heat_pump", "mini_split", "boiler", "other"]},
                        "issue_description": {"type": "string"},
                        "is_existing_customer": {"type": "boolean", "default": False},
                    },
                    "required": ["customer_name", "phone", "address", "city", "state", "zip_code", "preferred_date", "preferred_time", "service_type", "system_type", "issue_description"],
                },
                handler=book_appointment,
            ),
            tool(
                name="check_maintenance_plan",
                description="Check if customer has active maintenance plan (waives emergency fee)",
                parameters={
                    "type": "object",
                    "properties": {
                        "customer_phone": {"type": "string"},
                    },
                    "required": ["customer_phone"],
                },
                handler=check_maintenance_plan,
            ),
        ],
    )
    
    return phone, agent


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

async def main():
    """Run the HVAC agent server."""
    phone, agent = build_agent()
    
    port = int(os.getenv("PORT", "8000"))
    dashboard_token = os.getenv("DASHBOARD_TOKEN", "change-me-in-production")
    
    logger.info(f"Starting HVAC agent on port {port}")
    logger.info(f"Dashboard: http://localhost:{port}/dashboard (token: {dashboard_token})")
    logger.info(f"Webhook URL: {os.getenv('WEBHOOK_URL') or 'auto-tunnel'}")
    logger.info(f"LLM Provider: {os.getenv('LLM_PROVIDER', 'anthropic')}")
    
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