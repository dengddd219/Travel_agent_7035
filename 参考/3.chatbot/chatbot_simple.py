"""
Simple chatbot using Azure OpenAI client.
"""
from azure_openai_client import AzureOpenAIClient


class Chatbot:
    def __init__(self, system_message="You are a helpful assistant."):
        self.client = AzureOpenAIClient()
        self.system_message = system_message
        self.conversation_history = []

    def set_system_message(self, message):
        """Update the system message."""
        self.system_message = message

    def chat(self, user_input):
        """Send a message and get a response."""
        messages = [{"role": "system", "content": self.system_message}]
        messages.extend(self.conversation_history)
        messages.append({"role": "user", "content": user_input})

        response = self.client.get_response(messages)

        if isinstance(response, str) and response.startswith("Error:"):
            return response

        assistant_message = response.choices[0].message.content
        self.conversation_history.append({"role": "user", "content": user_input})
        self.conversation_history.append({"role": "assistant", "content": assistant_message})

        return assistant_message

    def clear_history(self):
        """Clear conversation history."""
        self.conversation_history = []

    def get_token_usage(self, user_input):
        """Get token usage for a single message."""
        messages = [{"role": "system", "content": self.system_message}]
        messages.append({"role": "user", "content": user_input})

        response = self.client.get_response(messages)

        if isinstance(response, str) and response.startswith("Error:"):
            return response

        return self.client.get_token_usage(response)


if __name__ == "__main__":
    import sys

    bot = Chatbot("You are a helpful coding assistant.")

    print("Chatbot initialized. Type 'quit' to exit.")
    print(f"Deployment: {bot.client.get_deployment_name()}")
    print("-" * 50)

    # Support command line arguments for non-interactive mode
    if len(sys.argv) > 1:
        user_input = " ".join(sys.argv[1:])
        response = bot.chat(user_input)
        print(f"\nUser: {user_input}")
        print(f"\nAssistant: {response}")
        usage = bot.get_token_usage(user_input)
        if isinstance(usage, dict):
            print(f"[Tokens: {usage['total_tokens']} | Cost: {usage['cost_display']}]")
    else:
        while True:
            user_input = input("\nYou: ")
            if user_input.lower() == "quit":
                break

            response = bot.chat(user_input)
            print(f"\nAssistant: {response}")

            # Show token usage
            usage = bot.get_token_usage(user_input)
            if isinstance(usage, dict):
                print(f"[Tokens: {usage['total_tokens']} | Cost: {usage['cost_display']}]")
