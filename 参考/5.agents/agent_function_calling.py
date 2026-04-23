# 实验一：单问题，每次只能执行一个function调用，且每次调用后都要等待用户输入才能继续下一步
# Find me the next event I can see from Asia and give me the cost for 5 hours of premium telescope time at normal priority.
# Generate that information in a report for HKU.

# 1. Find me the next event I can see from Asia 
# Answer: 它理应调用第一个function，只提了一个需求
# AGENT: The next visible event from Asia is the Lyrids meteor shower.
# - Event: Lyrids Meteor Shower  
# - Type: Meteor shower  
# - Peak date: April 22 (annual)  
# - Visible from: Asia (also Europe and North America)  

# Quick observing tips
# - Best viewing: late night through pre-dawn on the peak night (after midnight until just before dawn).  
# - Where to look: no telescope needed — lie back and scan the sky. Meteors appear to radiate from the constellation Lyra (near the bright star Vega), but they can appear anywhere.  
# - Conditions: dark sky away from city lights gives the best rates. Expect modest rates (~10–20/hour typical), though occasional stronger activity can occur.

# Would you like:
# - A tailored visibility/time estimate for a specific city in Asia?  
# - Moon phase for that night?  
# - A telescope observation booking and cost estimate for that date?
# Enter a prompt for the astronomy agent. Use 'quit' to exit.

# 2. Give me the cost for 5 hours of premium telescope time at normal priority.
# AGENT：是能够记住上下文的，因为是建立了conversion，但当前都是在同一个聊天内完成
# AGENT: The next visible event from Asia is the Lyrids meteor shower.

# - Event: Lyrids Meteor Shower  
# - Type: Meteor shower  
# - Peak date: April 22 (annual)  
# - Visible from: Asia (also Europe and North America)  

# Quick observing tips
# - Best viewing: late night through pre-dawn on the peak night (after midnight until just before dawn).  
# - Where to look: no telescope needed — lie back and scan the sky. Meteors appear to radiate from the constellation Lyra (near the bright star Vega), but they can appear anywhere.  
# - Conditions: dark sky away from city lights gives the best rates. Expect modest rates (~10–20/hour typical), though occasional stronger activity can occur.

# Would you like:
# - A tailored visibility/time estimate for a specific city in Asia?  
# - Moon phase for that night?  
# - A telescope observation booking and cost estimate for that date?
# Enter a prompt for the astronomy agent. Use 'quit' to exit.
# USER:   Give me the cost for 5 hours of premium telescope time at normal priority.
# AGENT: Next visible event from Asia:
# - Lyrids Meteor Shower — date: April 22 — visible from: Asia, Europe, North America.

# Cost for 5 hours of premium telescope time at normal priority:
# - Hourly rate (premium): $300
# - Base cost (5 hours): $1,500
# - Priority multiplier (normal): 1.25
# - Total cost: $1,875 (USD)

# Would you like me to book the time or generate an observation report for the Lyrids?

#USER: 3. Generate that information in a report for HKU.
# AGENT: 生成了 report_lyrids_meteor_shower_2026-04-08_1209.txt
# C:\Users\19841\Desktop\我的坚果云\7035 LLM\report_lyrids_meteor_shower_2026-04-08_1209.txt

# USER: 4. what you can do ?
# AGENT: 产生幻觉了呵呵

# 上面三次实验都非常简单，每次只执行和询问一个问题。

# 实验二：复杂问题，用户一次性提出多个需求，模型需要连续调用多个function来满足用户的需求，并且不需要用户在每次调用后都输入，直到所有需求都满足了才输出结果。
# User: Find me the next event I can see from Asia and give me the cost for 5 hours of premium telescope time at normal priority. Also, Generate that information in a report for HKU.
# AGENT: 产生了幻觉了，感觉是没有正确处理连续的function调用，或者说在一次对话里连续调用了三个function，但没有正确地把结果传递回模型，导致模型无法正确地生成最终的报告。
# USER: Find me the next event I can see from Asia and give me the cost for 5 hours of premium telescope time at normal priority. Also, Generate that information in a report for HKU.
# AGENT: 
# Enter a prompt for the astronomy agent. Use 'quit' to exit.
# USER: 

# STUCK!!!!!!
# Refer to v2
import os
import json
from urllib import response
from dotenv import load_dotenv

# Add references
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FunctionTool
from azure.identity import DefaultAzureCredential
from azure.ai.projects.models import PromptAgentDefinition, FunctionTool
from openai.types.responses.response_input_param import FunctionCallOutput, ResponseInputParam
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
# Determine the next visible astronomical event for a given location
def next_visible_event(location: str) -> str: # 根据当前时间，返回最近的下一个在指定位置可见的天文事件
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
#=====================================
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

        # Define the event function tool###########
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

        # Create a list to hold function call outputs that will be sent back as input to the agent
        input_list: ResponseInputParam = []

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
                input=input_list,
            )

            # Check the run status for failures
            if response.status == "failed":
                print(f"Response failed: {response.error}")

            # Process function calls
            for item in response.output:
                if item.type == "function_call":
                    # Retrieve the matching function tool
                    function_name = item.name
                    result = None
                    if item.name == "next_visible_event":
                        result = next_visible_event(**json.loads(item.arguments))
                    elif item.name == "calculate_observation_cost":
                        result = calculate_observation_cost(**json.loads(item.arguments))
                    elif item.name == "generate_observation_report":
                        result = generate_observation_report(**json.loads(item.arguments))

                    # Append the output text
                    input_list.append(
                        FunctionCallOutput(
                            type="function_call_output",
                            call_id=item.call_id,
                            output=result,
                        )
                    )

            # Send function call outputs back to the model and retrieve a response
            if input_list:
                response = openai_client.responses.create(
                    input=input_list,
                    previous_response_id=response.id,
                    extra_body={"agent_reference": {"name": agent.name, "type": "agent_reference"}},
                )
            # Display the agent's response
            print(f"AGENT: {response.output_text}")

        # Delete the agent when done
        # project_client.agents.delete_version(agent_name=agent.name, agent_version=agent.version)
        # print("Deleted agent.")


if __name__ == '__main__':
    main()

