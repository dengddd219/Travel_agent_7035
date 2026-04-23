# use Azure OpenAI to build a chatbot
# it starts with a greeting message and waits for user input from the console
# then it uses Azure OpenAI to generate a response
# the conversation continues until the user stops it

from azure_openai_client import AzureOpenAIClient

def chatbot():
    client = AzureOpenAIClient()
    messages = []
    # add a system message to define the bot behavior
    # Technical Support Bot
    messages.append({"role": "system",
                     "content": "You are a technical support bot. Provide clear and concise technical assistance."})
    # Casual and Fun Chatbot
    # messages.append({"role": "system",
    #                  "content": "You are a casual and fun chatbot. Engage the user with humor and light-hearted conversation while still providing useful information."})
    print("Welcome to the chatbot!")
    while True:
        user_input = input("You: ")
        if user_input.lower() == "exit":
            break
        messages=[] # uncomment this line to show that Azure OpenAI API request is stateless
        # q: what is a stateless API request?
        # a: a stateless API request does not store any information about the previous requests
        messages.append({"role": "user", "content": user_input})
        response = client.get_response(messages)
        bot_response = response.choices[0].message.content
        # add bot response to the conversation history
        messages.append({"role": "assistant", "content": bot_response})
        print(f"Bot: {bot_response}")
        # print token usage
        token_usage = client.get_token_usage(response.to_dict())
        print(f"Token usage: {token_usage}")

if __name__ == "__main__":
    chatbot()

"""
test the chatbot with the following conversation:

hi
why is it so fast for github copilot to generate code suggestions?
are code suggestions done locally or on the server and sent back over Internet?
but is my machine fast enough?
exit

"""