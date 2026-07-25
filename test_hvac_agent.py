#!/usr/bin/env python3
"""
Test script for HVAC agent - validates agent creation and tool/guardrail registration.
"""

import os
import asyncio

# Set test environment
os.environ['PATTER_TELEMETRY_DISABLED'] = '1'
os.environ['ANTHROPIC_API_KEY'] = 'test'
os.environ['DEEPGRAM_API_KEY'] = 'test'
os.environ['ELEVENLABS_API_KEY'] = 'test'
os.environ['TWILIO_ACCOUNT_SID'] = 'ACtest'
os.environ['TWILIO_AUTH_TOKEN'] = 'test'
os.environ['TWILIO_PHONE_NUMBER'] = '+15551234567'
os.environ['BUSINESS_NAME'] = 'Test HVAC'
os.environ['SERVICE_AREA'] = 'Test Area'

from hvac_agent import build_agent, on_call_start, on_call_end, on_metrics
from hvac_agent import dispatch_emergency, book_appointment, check_maintenance_plan

async def test_agent_creation():
    """Test that the agent builds with all components."""
    print("Testing agent creation...")
    
    phone, agent = build_agent()
    
    assert phone is not None, "Phone should be created"
    assert agent is not None, "Agent should be created"
    
    # Check tools
    tool_names = [t.get('name', 'unknown') for t in agent.tools]
    expected_tools = ['dispatch_emergency', 'book_appointment', 'check_maintenance_plan']
    for expected in expected_tools:
        assert expected in tool_names, f"Missing tool: {expected}"
    print(f"✓ Tools registered: {tool_names}")
    
    # Check guardrails
    guardrail_names = [g.get('name', 'unknown') for g in agent.guardrails]
    expected_guardrails = ['no_competitor_mentions', 'no_medical_legal_advice', 'emergency_keyword_trigger']
    for expected in expected_guardrails:
        assert expected in guardrail_names, f"Missing guardrail: {expected}"
    print(f"✓ Guardrails registered: {guardrail_names}")
    
    # Check variables
    assert 'business_name' in agent.variables, "Missing business_name variable"
    assert 'service_area' in agent.variables, "Missing service_area variable"
    print(f"✓ Variables: {list(agent.variables.keys())}")
    
    # Check system prompt has our formatting
    assert 'Test HVAC' in agent.system_prompt, "Business name not in system prompt"
    assert 'Test Area' in agent.system_prompt, "Service area not in system prompt"
    print(f"✓ System prompt formatted ({len(agent.system_prompt)} chars)")
    
    # Check first_message template (has {business_name} placeholder, resolved at runtime)
    assert "{business_name}" in agent.first_message, "First message template missing business_name"
    # Check that variables are set
    assert agent.variables.get("business_name") == "Test HVAC"
    print(f"✓ First message: {agent.first_message[:60]}...")
    
    return True


async def test_tool_handlers():
    """Test that tool handlers execute correctly."""
    print("\nTesting tool handlers...")
    
    # Test dispatch_emergency
    result = await dispatch_emergency(
        address="123 Main St, Los Angeles, CA 90001",
        issue="No heat, furnace not working",
        contact_name="John Doe",
        contact_phone="+15551234567",
        access_notes="Gate code 1234",
        gate_code="1234"
    )
    assert result['status'] == 'dispatched', f"Expected dispatched, got {result['status']}"
    assert 'tech_name' in result, "Missing tech_name in dispatch result"
    print(f"✓ dispatch_emergency: {result['dispatch_id']}")
    
    # Test book_appointment
    result = await book_appointment(
        customer_name="Jane Smith",
        phone="+15551234567",
        email="jane@example.com",
        address="456 Oak Ave",
        city="Los Angeles",
        state="CA",
        zip_code="90002",
        preferred_date="2026-07-25",
        preferred_time="10:00 AM",
        service_type="maintenance",
        system_type="furnace",
        issue_description="Annual tune-up",
        is_existing_customer=True
    )
    assert result['status'] == 'booked', f"Expected booked, got {result['status']}"
    assert 'appointment_id' in result, "Missing appointment_id"
    print(f"✓ book_appointment: {result['appointment_id']}")
    
    # Test check_maintenance_plan
    result = await check_maintenance_plan(customer_phone="+15551234567")
    assert 'has_plan' in result, "Missing has_plan"
    print(f"✓ check_maintenance_plan: {result}")
    
    return True


async def test_call_lifecycle_handlers():
    """Test call lifecycle handlers."""
    print("\nTesting call lifecycle handlers...")
    
    # Test on_call_start
    call_data = {"from": "+15551234567", "to": "+15557654321"}
    result = await on_call_start(call_data)
    assert 'variables' in result, "on_call_start should return variables dict"
    assert 'customer_name' in result['variables'], "Missing customer_name in variables"
    print(f"✓ on_call_start: returns {len(result['variables'])} variables")
    
    # Test on_call_end
    await on_call_end({
        "call_id": "test_123",
        "duration_seconds": 120,
        "cost_usd": 0.15,
        "recording_url": "https://example.com/recording.wav",
        "transcript": "Agent: Hello... User: Hi..."
    })
    print(f"✓ on_call_end: executed without error")
    
    # Test on_metrics
    await on_metrics({
        "call_id": "test_123",
        "cost": {"total": 0.15, "stt": 0.01, "tts": 0.02, "llm": 0.05, "telephony": 0.07},
        "latency_p95": {"total_ms": 800, "stt_ms": 200, "llm_ms": 400, "tts_ms": 200}
    })
    print(f"✓ on_metrics: executed without error")
    
    return True


async def test_prompt_formatting():
    """Test that the system prompt is properly formatted with variables."""
    print("\nTesting prompt formatting...")
    
    phone, agent = build_agent()
    
    # The agent should have resolved variables in the system prompt
    assert 'Test HVAC' in agent.system_prompt
    assert 'Test Area' in agent.system_prompt
    assert 'Alex' in agent.system_prompt  # Agent name
    assert 'EMERGENCY PROTOCOL' in agent.system_prompt
    assert 'APPOINTMENT BOOKING' in agent.system_prompt
    assert 'KNOWLEDGE BASE' in agent.system_prompt
    assert 'GUARDRAILS' in agent.system_prompt
    print(f"✓ System prompt contains all sections ({len(agent.system_prompt)} chars)")
    
    return True


async def main():
    print("=" * 60)
    print("ALWAYSANSWER AI - HVAC Agent Test Suite")
    print("=" * 60)
    
    tests = [
        test_agent_creation,
        test_tool_handlers,
        test_call_lifecycle_handlers,
        test_prompt_formatting,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            await test()
            passed += 1
        except Exception as e:
            print(f"✗ {test.__name__} FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)