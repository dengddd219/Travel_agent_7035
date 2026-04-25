
"""
Sample: Hotel Booking Conditional Workflow

This sample demonstrates a conditional workflow using the Microsoft Agent Framework
that routes based on hotel availability.

Workflow:
1. User provides a destination city
2. Agent checks hotel availability using a tool
3. Conditional routing:
   - If NO availability → Suggest alternative city
   - If availability → Suggest booking
4. Display result with HTML formatting

Key Concepts:
- WorkflowBuilder with conditional edges
- AgentExecutor wrapping AI agents
- @executor decorator for custom logic
- Pydantic models for structured outputs
- @tool decorator for tools
- OpenAIChatClient integration
"""
import os
import asyncio
import json
from typing import Annotated, Any, Never

from agent_framework import (
    AgentExecutor,
    AgentExecutorRequest,
    AgentExecutorResponse,
    Message,
    WorkflowBuilder,
    WorkflowContext,
    tool,
    executor,
)
from agent_framework.openai import OpenAIChatClient
from dotenv import load_dotenv
from pydantic import BaseModel

# ============================================================================
# STEP 1: PYDANTIC MODELS FOR STRUCTURED OUTPUTS
# ============================================================================


class BookingCheckResult(BaseModel):
    """Result from checking hotel availability at a destination."""

    destination: str
    has_availability: bool
    message: str


class AlternativeResult(BaseModel):
    """Suggested alternative destination when no rooms available."""

    alternative_destination: str
    reason: str


class BookingConfirmation(BaseModel):
    """Booking suggestion when rooms are available."""

    destination: str
    action: str
    message: str


# ============================================================================
# STEP 2: HOTEL BOOKING TOOL (AGENT FUNCTION)
# ============================================================================


@tool(description="Check hotel room availability for a destination city")
def hotel_booking(destination: Annotated[str, "The destination city to check for hotel rooms"]) -> str:
    """
    Simulates checking hotel room availability.

    For demo purposes:
    - Stockholm, Seattle, Tokyo have rooms
    - All other cities don't have rooms

    Returns:
        JSON string with availability status
    """
    print(f"🔍 Checking hotel availability in {destination}...")

    # Simulate availability check
    cities_with_rooms = ["stockholm", "seattle", "tokyo", "london", "amsterdam"]
    has_rooms = destination.lower() in cities_with_rooms

    result = {"has_availability": has_rooms, "destination": destination}

    return json.dumps(result)


# ============================================================================
# STEP 3: CONDITION FUNCTIONS FOR ROUTING
# ============================================================================


def _extract_response_payload(message: Any) -> str | None:
    """Extract a JSON payload string from Agent Framework response objects."""
    if isinstance(message, AgentExecutorResponse):
        agent_response = message.agent_response
    else:
        agent_response = message

    if isinstance(agent_response, str):
        return agent_response

    value = getattr(agent_response, "value", None)
    if value is not None:
        # Structured responses may already be a dict or Pydantic-like object.
        if hasattr(value, "model_dump_json"):
            return value.model_dump_json()
        if isinstance(value, dict):
            return json.dumps(value)
        if isinstance(value, str):
            return value

    text = getattr(agent_response, "text", None)
    if isinstance(text, str):
        return text

    return None


def _parse_booking_check_result(message: Any) -> BookingCheckResult | None:
    payload = _extract_response_payload(message)
    if payload is None:
        return None

    try:
        return BookingCheckResult.model_validate_json(payload)
    except Exception as e:
        print(f"⚠️  Error parsing availability result: {e}")
        return None


def has_availability_condition(message: Any) -> bool:
    """
    Condition for routing when hotels ARE available.

    Args:
        message: Message from upstream executor (should be AgentExecutorResponse)

    Returns:
        True if availability exists, False otherwise
    """
    result = _parse_booking_check_result(message)
    if result is None:
        return False

    print(f"✅ Availability check: {result.has_availability} for {result.destination}")
    return result.has_availability


def no_availability_condition(message: Any) -> bool:
    """
    Condition for routing when hotels are NOT available.

    Args:
        message: Message from upstream executor

    Returns:
        True if no availability, False otherwise
    """
    result = _parse_booking_check_result(message)
    if result is None:
        return False
    if not result.has_availability:
        print(f"❌ No availability for {result.destination}")
    return not result.has_availability


# ============================================================================
# STEP 4: DISPLAY EXECUTOR (Custom transformation)
# ============================================================================


@executor(id="display_result")
async def display_result(response: AgentExecutorResponse, ctx: WorkflowContext[Never, str]) -> None:
    """
    Display the final result as workflow output.

    This executor receives the final agent response and yields it as output.
    """
    print(f"📤 Yielding workflow output...")
    payload = _extract_response_payload(response)
    if payload is None:
        print("⚠️  Could not serialize final response payload")
        return
    await ctx.yield_output(payload)


# ============================================================================
# STEP 5: MAIN WORKFLOW FUNCTION
# ============================================================================


async def main() -> None:
    """
    Main function to build and execute the hotel booking workflow.
    """
    # Load environment variables
    load_dotenv()

    # Verify configuration
    print("=" * 80)
    print("🏨 HOTEL BOOKING CONDITIONAL WORKFLOW")
    print("=" * 80)

    # Azure OpenAI
    chat_client = OpenAIChatClient(
        model=os.getenv("AZURE_OPENAI_RESPONSES_DEPLOYMENT_NAME"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    )

    print("\n" + "=" * 80)
    print("STEP 1: Creating AI Agents with Structured Outputs")
    print("=" * 80)

    # Agent 1: Check availability
    availability_agent = AgentExecutor(
        chat_client.as_agent(
            instructions=(
                "You are a hotel booking assistant that checks room availability. "
                "Use the hotel_booking tool to check if rooms are available at the destination. "
                "Return JSON with fields: destination (string), has_availability (bool), and message (string). "
                "The message should summarize the availability status."
            ),
            tools=[hotel_booking],
            default_options={"response_format": BookingCheckResult},
        ),
        id="availability_agent",
    )
    print("✅ Created availability_agent with hotel_booking tool")

    # Agent 2: Suggest alternative (when no rooms)
    alternative_agent = AgentExecutor(
        chat_client.as_agent(
            instructions=(
                "You are a helpful travel assistant. When a user cannot find hotels in their requested city, "
                "suggest an alternative nearby city that has availability. "
                "Return JSON with fields: alternative_destination (string) and reason (string). "
                "Choose from: Stockholm, Seattle, Tokyo, London, or Amsterdam (these have rooms). "
                "Make your suggestion sound appealing and helpful."
            ),
            default_options={"response_format": AlternativeResult},
        ),
        id="alternative_agent",
    )
    print("✅ Created alternative_agent for suggesting other cities")

    # Agent 3: Suggest booking (when rooms available)
    booking_agent = AgentExecutor(
        chat_client.as_agent(
            instructions=(
                "You are a booking assistant. The user has found available hotel rooms. "
                "Encourage them to book by highlighting the destination's appeal. "
                "Return JSON with fields: destination (string), action (string), and message (string). "
                "The action should be 'book_now' and message should be encouraging."
            ),
            default_options={"response_format": BookingConfirmation},
        ),
        id="booking_agent",
    )
    print("✅ Created booking_agent for confirming bookings")

    print("\n" + "=" * 80)
    print("STEP 2: Building Workflow with Conditional Edges")
    print("=" * 80)

    # Build the workflow
    workflow = (
        WorkflowBuilder(start_executor=availability_agent, output_executors=[display_result])
        # .set_start_executor()
        # NO AVAILABILITY PATH: availability_agent → alternative_agent → display_result
        .add_edge(availability_agent, alternative_agent, condition=no_availability_condition)
        .add_edge(alternative_agent, display_result)
        # HAS AVAILABILITY PATH: availability_agent → booking_agent → display_result
        .add_edge(availability_agent, booking_agent, condition=has_availability_condition)
        .add_edge(booking_agent, display_result)
        .build()
    )

    print("✅ Workflow built with conditional routing:")
    print("   - If NO availability → suggest alternative")
    print("   - If availability → suggest booking")

    # ============================================================================
    # TEST CASE 1: City WITHOUT availability (Paris)
    # ============================================================================
    print("\n" + "=" * 80)
    print("TEST CASE 1: Checking Paris (NO AVAILABILITY)")
    print("=" * 80)

    request1 = AgentExecutorRequest(
        messages=[Message(role="user", contents=["I want to book a hotel in Paris"])], should_respond=True
    )

    events1 = await workflow.run(request1)
    outputs1 = events1.get_outputs()

    if outputs1:
        print("\n📊 WORKFLOW OUTPUT (Paris):")
        print("-" * 80)
        result1_payload = _extract_response_payload(outputs1[0])
        if result1_payload is None:
            raise RuntimeError("Failed to extract final workflow output for Paris case")
        result1 = AlternativeResult.model_validate_json(result1_payload)
        print(f"🏨 Alternative Destination: {result1.alternative_destination}")
        print(f"💡 Reason: {result1.reason}")
        print("-" * 80)

    # ============================================================================
    # TEST CASE 2: City WITH availability (Stockholm)
    # ============================================================================
    print("\n" + "=" * 80)
    print("TEST CASE 2: Checking Stockholm (HAS AVAILABILITY)")
    print("=" * 80)

    request2 = AgentExecutorRequest(
        messages=[Message(role="user", contents=["I want to book a hotel in Stockholm"])], should_respond=True
    )

    events2 = await workflow.run(request2)
    outputs2 = events2.get_outputs()

    if outputs2:
        print("\n📊 WORKFLOW OUTPUT (Stockholm):")
        print("-" * 80)
        result2_payload = _extract_response_payload(outputs2[0])
        if result2_payload is None:
            raise RuntimeError("Failed to extract final workflow output for Stockholm case")
        result2 = BookingConfirmation.model_validate_json(result2_payload)
        print(f"🏨 Destination: {result2.destination}")
        print(f"✅ Action: {result2.action}")
        print(f"💬 Message: {result2.message}")
        print("-" * 80)

    print("\n" + "=" * 80)
    print("✅ WORKFLOW DEMO COMPLETE!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())