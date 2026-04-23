# 实验二：复杂问题，用户一次性提出多个需求，模型需要连续调用多个function来满足用户的需求，并且不需要用户在每次调用后都输入，直到所有需求都满足了才输出结果。
# USER: Find me the next event I can see from Asia and give me the cost for 5 hours of premium telescope time at normal priority. Also, Generate that information in a report for HKU.
# AGENT: Here’s what I found and the requested report.

# Next visible event from Asia:
# - Event: Lyrids Meteor Shower
# - Type: meteor shower
# - Date (peak): April 22
# - Visible from: Asia (and other regions)

# Cost for 5 hours of premium telescope time at normal priority:
# - Hourly rate (premium): $300.00
# - Priority multiplier (normal): 1.25
# - Base cost (300 x 5): $1,500.00
# - Total cost (with priority): $1,875.00

# Report generated for HKU:
# - File: report_lyrids_meteor_shower_2026-04-08_1217.txt
# - Contents summary: includes event details (Lyrids Meteor Shower, Apr 22), observation location (Asia), telescope tier (premium), requested hours (5), priority (normal), and cost estimate ($1,875.00). Observer listed as HKU.

# If you’d like, I can:
# - Open or display the full report contents here,
# - Adjust the observation time or priority,
# - Book the telescope time (if you provide billing/authorization details), or
# - Provide observing tips for viewing the Lyrids from Hong Kong (best dates/times, moon phase, direction, equipment).
# Enter a prompt for the astronomy agent. Use 'quit' to exit.
# USER: 
# AGENT: Do you want anything else with that report? Options I can do now:
# - Display the full report contents here,
# - Adjust hours, priority, or telescope tier and recalc cost,
# - Book/schedule the observation (you’d need to provide authorization details),
# - Provide observing tips for viewing the Lyrids from Hong Kong (best times, moon phase, direction, equipment),
# - Find other upcoming events visible from Asia.

import os
import json
from dotenv import load_dotenv

# Add references
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.projects.models import PromptAgentDefinition, FunctionTool
from datetime import datetime

def _load_events(file_path: str = None) -> list:
    if file_path is None:
        file_path = os.path.join(os.path.dirname(__file__), "data", "events.txt")
    events = []
    with open(file_path) as f:
        for line in f:
            parts = line.strip().split("|")
            if len(parts) == 4:
                month, day = map(int, parts[2].split("-"))
                events.append((
                    parts[0],                          # name
                    parts[1],                          # type
                    month * 100 + day,                 # sortable month-day int
                    parts[2],                          # month-day string
                    set(parts[3].split(";")),          # locations as a set
                ))
    events.sort(key=lambda e: e[2])
    print("Events loaded: ", events)
    return events


def _load_rates(file_path: str) -> dict:
    rates = {}
    with open(file_path) as f:
        for line in f:
            parts = line.strip().split("|")
            if len(parts) == 2:
                rates[parts[0]] = float(parts[1])
    print("Rates loaded: ", rates)
    return rates

EVENTS = _load_events()
TELESCOPE_RATES = _load_rates(os.path.join(os.path.dirname(__file__), "data", "telescope_rates.txt"))
PRIORITY_MULTIPLIERS = _load_rates(os.path.join(os.path.dirname(__file__), "data", "priority_multipliers.txt"))

# Determine the next visible astronomical event for a given location
def next_visible_event(location: str) -> str:
    """Returns the next visible astronomical event for a location."""
    today = int(datetime.now().strftime("%m%d"))
    loc = location.lower().replace(" ", "_")

    # Retrieve the next event visible from the location, starting with events later this year
    for name, event_type, date, date_str, locs in EVENTS:
        if loc in locs and date >= today:
            return json.dumps({"event": name, "type": event_type, "date": date_str, "visible_from": sorted(locs)})

    return json.dumps({"message": f"No upcoming events found for {location}."})

# Calculate the cost of telescope observation time based on the tier, hours, and priority
def calculate_observation_cost(telescope_tier: str, hours: float, priority: str) -> str:
    """Calculates the cost of telescope observation time."""
    tier = telescope_tier.lower()
    pri = priority.lower()

    if tier not in TELESCOPE_RATES:
        return json.dumps({"error": f"Unknown telescope tier '{telescope_tier}'. Choose from: {', '.join(TELESCOPE_RATES)}"})

    if pri not in PRIORITY_MULTIPLIERS:
        return json.dumps({"error": f"Unknown priority '{priority}'. Choose from: {', '.join(PRIORITY_MULTIPLIERS)}"})

    if hours <= 0:
        return json.dumps({"error": "Hours must be greater than zero."})

    base_cost = TELESCOPE_RATES[tier] * hours
    multiplier = PRIORITY_MULTIPLIERS[pri]
    total_cost = base_cost * multiplier

    return json.dumps({
        "telescope_tier": tier,
        "hours": hours,
        "hourly_rate": TELESCOPE_RATES[tier],
        "priority": pri,
        "priority_multiplier": multiplier,
        "base_cost": base_cost,
        "total_cost": total_cost
    })

# Generate an observation report summarizing the details of an astronomical observation session
def generate_observation_report(event_name: str, location: str, telescope_tier: str, hours: float, priority: str, observer_name: str) -> str:
    """
    Generates an observation session report and saves it to a file.

    Returns:
        JSON string with the file path of the generated report.
    """
    cost_result = json.loads(calculate_observation_cost(telescope_tier, hours, priority))
    event_result = json.loads(next_visible_event(location))

    if "error" in cost_result:
        return json.dumps(cost_result)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    filename = f"report_{event_name.replace(' ', '_').lower()}_{timestamp.replace(':', '').replace(' ', '_')}.txt"

    report = f"""======================================
CONTOSO OBSERVATORIES - SESSION REPORT
======================================
Date:           {timestamp}
Observer:       {observer_name}
Event:          {event_name}
Location:       {location}

NEXT VISIBLE EVENT
  Event:        {event_result.get('event', 'N/A')}
  Date:         {event_result.get('date', 'N/A')}

TELESCOPE BOOKING
  Tier:         {cost_result['telescope_tier']}
  Hours:        {cost_result['hours']}
  Hourly Rate:  ${cost_result['hourly_rate']:.2f}
  Priority:     {cost_result['priority']}
  Multiplier:   {cost_result['priority_multiplier']}x

COST SUMMARY
  Base Cost:    ${cost_result['base_cost']:.2f}
  Total Cost:   ${cost_result['total_cost']:.2f}
======================================
"""

    with open(filename, "w") as f:
        f.write(report)

    return json.dumps({"status": "Report generated", "file": filename})


def _run_tool_call(item) -> str:
    """Executes a tool call item and returns a serialized tool output string."""
    try:
        args = json.loads(item.arguments or "{}")
    except json.JSONDecodeError:
        return json.dumps({"error": f"Invalid JSON arguments for function '{item.name}'"})

    if item.name == "next_visible_event":
        return next_visible_event(**args)
    if item.name == "calculate_observation_cost":
        return calculate_observation_cost(**args)
    if item.name == "generate_observation_report":
        return generate_observation_report(**args)
    return json.dumps({"error": f"Unknown function: {item.name}"})

def main():
    # Load environment variables from .env file
    load_dotenv()
    project_endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    model_deployment = os.getenv("FOUNDRY_PROJECT_DEPLOYMENT")

    # Connect to the project client
    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(endpoint=project_endpoint, credential=credential) as project_client,
        project_client.get_openai_client() as openai_client,
    ):

        # Define the event function tool
        event_tool = FunctionTool(
            name="next_visible_event",
            description="Get the next visible event in a given location.",
            parameters={
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "continent to find the next visible event in (e.g. 'north_america', 'south_america', 'australia')",
                    },
                },
                "required": ["location"],
                "additionalProperties": False,
            },
            strict=True,
        )

        # Define the observation cost function tool
        cost_tool = FunctionTool(
            name="calculate_observation_cost",
            description="Calculate the cost of an observation based on the telescope tier, number of hours, and priority level.",
            parameters={
                "type": "object",
                "properties": {
                    "telescope_tier": {
                        "type": "string",
                        "description": "the tier of the telescope (e.g. 'standard', 'advanced', 'premium')",
                    },
                    "hours": {
                        "type": "number",
                        "description": "the number of hours for the observation",
                    },
                    "priority": {
                        "type": "string",
                        "description": "the priority level of the observation (e.g. 'low', 'normal', 'high')",
                    },
                },
                "required": ["telescope_tier", "hours", "priority"],
                "additionalProperties": False,
            },
            strict=True,
        )

        # Define the observation report generation function tool
        report_tool = FunctionTool(
            name="generate_observation_report",
            description="Generate a report summarizing the details of an astronomical observation session.",
            parameters={
                "type": "object",
                "properties": {
                    "event_name": {
                        "type": "string",
                        "description": "the name of the astronomical event being observed",
                    },
                    "location": {
                        "type": "string",
                        "description": "the location of the observation (e.g. 'north_america', 'south_america', 'australia')",
                    },
                    "telescope_tier": {
                        "type": "string",
                        "description": "the tier of the telescope used for the observation (e.g. 'standard', 'advanced', 'premium')",
                    },
                    "hours": {
                        "type": "number",
                        "description": "the number of hours for the observation",
                    },
                    "priority": {
                        "type": "string",
                        "description": "the priority level of the observation (e.g. 'low', 'normal', 'high')",
                    },
                    "observer_name": {
                        "type": "string",
                        "description": "the name of the person who conducted the observation",
                    },
                },
                "required": ["event_name", "location", "telescope_tier", "hours", "priority", "observer_name"],
                "additionalProperties": False,
            },
            strict=True,
        )

        # Create a new agent with the function tools
        agent = project_client.agents.create_version(
            agent_name="astronomy-agent",
            definition=PromptAgentDefinition(
                model=model_deployment,
                instructions=
                """You are an astronomy observations assistant that helps users find 
                information about astronomical events and calculate telescope rental costs. 
                Use the available tools to assist users with their inquiries.""",
                tools=[event_tool, cost_tool, report_tool],
            ),
        )
        print("Agent created: ", agent.id, agent.name, agent.version)

        # Create a thread for the chat session
        conversation = openai_client.conversations.create()

        while True:
            user_input = input("Enter a prompt for the astronomy agent. Use 'quit' to exit.\nUSER: ").strip()
            if user_input.lower() == "quit":
                print("Exiting chat.")
                break

            # Send a prompt to the agent
            openai_client.conversations.items.create(
                conversation_id=conversation.id,
                items=[{"type": "message", "role": "user", "content": user_input}],
            )

            # Retrieve the agent's response, which may include function calls
            response = openai_client.responses.create(
                conversation=conversation.id,
                extra_body={"agent_reference": {"name": agent.name, "type": "agent_reference"}},
            )

            # Check the run status for failures
            if response.status == "failed":
                print(f"Response failed: {response.error}")

            turn_failed = False
            # 主要区别===============================
            # while 嵌套循环，直到没有function_call类型的输出了才break，
            # 在这期间如果有任何一次失败了就标记turn_failed并break，
            # 最后根据turn_failed来决定是否继续下一轮输入
            # Keep resolving tools until the model returns plain assistant text.
            while True:
                # Check for any pending function calls in the response output
                pending_calls = [item for item in response.output if item.type == "function_call"]
                if not pending_calls:
                    break

                tool_outputs = []
                for item in pending_calls:
                    if not item.call_id:
                        print(f"Tool call failed: missing call_id for function '{item.name}'")
                        turn_failed = True
                        break

                    result = _run_tool_call(item)
                    tool_outputs.append(
                        {
                            "type": "function_call_output",
                            "call_id": item.call_id,
                            "output": result,
                        }
                    )

                if turn_failed:
                    break

                response = openai_client.responses.create(
                    input=tool_outputs,
                    conversation=conversation.id, 
                    # 可以多个agent共用一个conversation，
                    # 这样用户就不需要每次都输入了，
                    # agent会根据之前的对话内容和工具调用结果来决定下一步要做什么，
                    # 直到所有需求都满足了才输出结果。
                    extra_body={"agent_reference": {"name": agent.name, "type": "agent_reference"}},
                )

                if response.status == "failed":
                    print(f"Response failed: {response.error}")
                    turn_failed = True
                    break

            if turn_failed:
                print("AGENT: Turn failed due to unresolved tool calls. Please retry your prompt.")
                continue

            # Display the agent's response
            print(f"AGENT: {response.output_text or '(No text response returned.)'}")

        # Delete the agent when done
        # project_client.agents.delete_version(agent_name=agent.name, agent_version=agent.version)
        # print("Deleted agent.")


if __name__ == '__main__':
    main()

# test prompts:
# Find me the next event I can see from Asia and give me the cost for 5 hours of premium telescope time at normal priority.
# Generate that information in a report for HKU.
# Generate a report for the next event in Africa observed by HKUBS for 3 hours of premium telescope time at the urgent priority.