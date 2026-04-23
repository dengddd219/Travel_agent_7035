from openai import OpenAI
import os
from dotenv import load_dotenv

def main():

    try:
        # Get configuration settings
        load_dotenv()

        # Initialize the OpenAI client
        openai_client = OpenAI(
            base_url="https://"+os.getenv("FOUNDRY_PROJECT_RESOURCE")+".openai.azure.com/openai/v1/",
            api_key=os.getenv("FOUNDRY_PROJECT_API_KEY")
        )
        model_deployment = os.getenv("FOUNDTRY_PROJECT_DEPLOYMENT")

        # Track responses under the newer Responses API
        last_response_id = None
        # Loop until the user wants to quit
        while True:
            input_text = input('\nEnter a prompt (or type "quit" to exit): ')
            if input_text.lower() == "quit":
                break
            if len(input_text) == 0:
                print("Please enter a prompt.")
                continue

            # 1. Get a response using the widely used Chat Completions API
            completion = openai_client.chat.completions.create(
                model=model_deployment,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful AI assistant that answers questions and provides information."
                    },
                    {
                        "role": "user",
                        "content": input_text
                    }
                ]
            )
            print(completion.choices[0].message.content)

            # 2. Get a response using the newer Responses API
            # response = openai_client.responses.create(
            #     model=model_deployment,
            #     instructions="You are a helpful AI assistant that answers questions and provides information.",
            #     input=input_text,
            #     previous_response_id=last_response_id,
            # )
            # print(response.output_text)
            # last_response_id = response.id

            # 3. Get a response using the newer Responses API with Streaming
            # stream = openai_client.responses.create(
            #     model=model_deployment,
            #     instructions="You are a helpful AI assistant that answers questions and provides information.",
            #     input=input_text,
            #     previous_response_id=last_response_id,
            #     stream=True
            # )
            # for event in stream:
            #     if event.type == "response.output_text.delta":
            #         print(event.delta, end="")
            #     elif event.type == "response.completed":
            #         last_response_id = event.response.id
            # print()

    except Exception as ex:
        print(ex)

if __name__ == '__main__':
    main()

# Test query:  Tell me about the ELIZA chatbot.
# follow-up prompt:  How does it compare to modern LLMs?