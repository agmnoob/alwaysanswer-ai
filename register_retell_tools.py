"""
register_retell_tools.py — Register Aria's 3 custom tools on the bound LLM.

Run AFTER deploy (Retell rejects non-public tool URLs). Set PUBLIC_BASE to the
here.now URL, e.g.:  PUBLIC_BASE=https://alwaysanswer-ai.here.now python3 register_retell_tools.py
"""
import os
import retell
from retell.types.llm_create_params import (
    GeneralToolCustomTool, GeneralToolCustomToolParameters,
)

LLM_ID = os.getenv("LLM_ID", "llm_18b0894dc9c0232c9ba4860ae89f")
PUBLIC_BASE = os.getenv("PUBLIC_BASE", "").rstrip("/")
if not PUBLIC_BASE or "localhost" in PUBLIC_BASE or "127.0.0.1" in PUBLIC_BASE:
    raise SystemExit("Set PUBLIC_BASE to the public here.now URL (Retell rejects localhost).")

client = retell.Retell(api_key=os.getenv("RETELL_API_KEY", "key_a2bc4c162c9b896515c2733dab2d"))

with open(os.path.join(os.path.dirname(__file__), "aria_prompt_v3.txt")) as f:
    prompt = f.read()

def custom(name, description, params_props, required):
    return GeneralToolCustomTool(
        type="custom", name=name, description=description,
        url=f"{PUBLIC_BASE}/api/{name}", method="POST", parameter_type="json",
        execution_message_type="static_text",
        execution_message_description="Checking our calendar...",
        speak_during_execution=True, speak_after_execution=True, timeout_ms=8000,
        parameters=GeneralToolCustomToolParameters(
            type="object", properties=params_props, required=required),
    )

check_tool = custom(
    "check_availability",
    "Read the OWNER's Google Calendar free/busy and return the next open demo slots. Call this FIRST when the prospect wants a demo.",
    {"max_slots": {"type": "integer", "description": "How many slots to return (default 3)"},
     "days_ahead": {"type": "integer", "description": "Lookahead window in days (default 14)"}},
    [],
)

book_tool = custom(
    "book_appointment",
    "Book the demo directly onto the OWNER's calendar when the prospect picks a slot. Call after they choose from check_availability.",
    {"prospect_name": {"type": "string", "description": "Caller first and last name"},
     "business_name": {"type": "string", "description": "Prospect company name"},
     "phone": {"type": "string", "description": "Caller phone E.164"},
     "datetime_slot": {"type": "string", "description": "Spoken slot, e.g. 'Tuesday July 28 at 10 AM'"},
     "start_iso": {"type": "string", "description": "Exact ISO start returned by check_availability"}},
    ["prospect_name", "business_name", "phone", "datetime_slot"],
)

cb_tool = custom(
    "send_callback",
    "Queue a personal callback when the prospect refuses any slot and insists on a callback instead.",
    {"prospect_name": {"type": "string", "description": "Caller first and last name"},
     "business_name": {"type": "string", "description": "Prospect company name"},
     "phone": {"type": "string", "description": "Caller phone E.164"},
     "notes": {"type": "string", "description": "Context: trade, pain, preferred times"}},
    ["prospect_name", "business_name", "phone"],
)

res = client.llm.update(
    llm_id=LLM_ID, model="gpt-4.1", general_prompt=prompt,
    general_tools=[check_tool, book_tool, cb_tool],
)
print("OK — tools registered on", res.llm_id)
print("tools:", [t.get("name") for t in (res.general_tools or [])])
