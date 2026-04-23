import os
import json
from openai import AzureOpenAI
from openai import OpenAI
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Create a .env File: In your project directory, create a file named .env.
# Add Variables: Inside the .env file, define your variables in the format: NAME=VALUE.
# For example, you can define the AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY variables.
# Load Variables in Your Code: Use the python-dotenv package to load these variables in your Python script.
load_dotenv()  # Load environment variables from .env file

# 1. Azure OpenAI API (old; API key shared by instructor for all students to use)
# Initialize the Azure OpenAI client
# client = AzureOpenAI(
#     azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
#     api_key=os.getenv("AZURE_OPENAI_API_KEY"),
#     api_version=os.getenv("AZURE_OPENAI_API_VERSION")
# )
# # Define the deployment you want to use for your chat completions API calls
# deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT") # gpt-4.1-mini, gpt-4.1, gpt-5-mini, etc.

# 2. Microsoft Foundry OpenAI API (new; Foundry project API key shared by instructor)
# Initialize the Microsoft Foundry OpenAI client
client = OpenAI(
    base_url="https://"+os.getenv("FOUNDRY_PROJECT_RESOURCE")+".openai.azure.com/openai/v1/",
    api_key=os.getenv("FOUNDRY_PROJECT_API_KEY")
)
# Define the deployment you want to use for your chat completions API calls
deployment_name = os.getenv("FOUNDTRY_PROJECT_DEPLOYMENT") # gpt-5-mini, gpt-4.1-mini, etc.
# Simplified weather data
WEATHER_DATA = {
    "tokyo": {"temperature": "10", "unit": "celsius"},
    "san francisco": {"temperature": "72", "unit": "fahrenheit"},
    "paris": {"temperature": "22", "unit": "celsius"}
}

# Simplified timezone data
TIMEZONE_DATA = {
    "tokyo": "Asia/Tokyo",
    "san francisco": "America/Los_Angeles",
    "paris": "Europe/Paris"
}

def get_current_weather(location, unit=None):
    """Get the current weather for a given location"""
    print(f"get_current_weather called with location: {location}, unit: {unit}")
    location_lower = location.lower()

    for key in WEATHER_DATA:
        if key in location_lower:
            print(f"Weather data found for {key}")
            weather = WEATHER_DATA[key]
            return json.dumps({
                "location": location,
                "temperature": weather["temperature"],
                "unit": unit if unit else weather["unit"]
            })

    print(f"No weather data found for {location_lower}")
    return json.dumps({"location": location, "temperature": "unknown"})


def get_current_time(location):
    """Get the current time for a given location"""
    print(f"get_current_time called with location: {location}")
    location_lower = location.lower()

    for key, timezone in TIMEZONE_DATA.items():
        if key in location_lower:
            print(f"Timezone found for {key}")
            current_time = datetime.now(ZoneInfo(timezone)).strftime("%I:%M %p")
            return json.dumps({
                "location": location,
                "current_time": current_time
            })

    print(f"No timezone data found for {location_lower}")
    return json.dumps({"location": location, "current_time": "unknown"})

def run_conversation():
    # Initial user message
    messages = [{"role": "user", "content": "What's the weather and current time in San Francisco?"}]
    # messages = [{"role": "user", "content": "What's the weather and current time in San Francisco and Paris?"}]

    # Define the functions for the model
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_current_weather",
                "description": "Get the current weather in a given location",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "The city name, e.g. San Francisco",
                        },
                        "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                    },
                    "required": ["location"],
                },
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_current_time",
                "description": "Get the current time in a given location",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "The city name, e.g. San Francisco",
                        },
                    },
                    "required": ["location"],
                },
            }
        }
    ]

    # First API call: Ask the model to use the functions
    response = client.chat.completions.create(
        model=deployment_name,
        messages=messages,
        tools=tools,
        tool_choice="auto",
    )

    # Process the model's response
    response_message = response.choices[0].message
    messages.append(response_message)

    print("Model's response:")
    print(response_message)

    # Handle function calls
    if response_message.tool_calls:
        for tool_call in response_message.tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            print(f"Function call: {function_name}")
            print(f"Function arguments: {function_args}")

            if function_name == "get_current_weather":
                function_response = get_current_weather(
                    location=function_args.get("location"),
                    unit=function_args.get("unit")
                )
            elif function_name == "get_current_time":
                function_response = get_current_time(
                    location=function_args.get("location")
                )
            else:
                function_response = json.dumps({"error": "Unknown function"})

            messages.append({
                "tool_call_id": tool_call.id,
                "role": "tool",
                "name": function_name,
                "content": function_response,
            })
    else:
        print("No tool calls were made by the model.")
    # print(messages)
    # Second API call: Get the final response from the model
    final_response = client.chat.completions.create(
        model=deployment_name,
        messages=messages,
    )

    return final_response.choices[0].message.content


# Run the conversation and print the result
print(run_conversation())