# Before running the sample:
#    pip install azure-ai-projects>=2.0.0
import os
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from dotenv import load_dotenv

# import logging
# logging.basicConfig(level=logging.INFO)
# logging.getLogger("azure.identity").setLevel(logging.INFO)

def main():
    load_dotenv()
    # Initialize the project client
    project_endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT")

    if not project_endpoint:
        print("Error: FOUNDRY_PROJECT_ENDPOINT environment variable not set")
        print("Please set it in your .env file or environment")
        return

    print("Connecting to Microsoft Foundry project...")
    project_client = AIProjectClient(
        credential=DefaultAzureCredential(),
        endpoint=project_endpoint
    )
    # Get the OpenAI client for Responses API
    openai_client = project_client.get_openai_client()

    my_agent = "allm-course-agent"
    my_version = "1"

    # Reference the agent to get a response
    response = openai_client.responses.create(
        input=[{"role": "user", "content": "Tell me what you can help with."}],
        extra_body={"agent_reference": {"name": my_agent, "version": my_version, "type": "agent_reference"}},
    )

    print(f"Response output: {response.output_text}")

if __name__ == "__main__":
    main()
