import streamlit as st
from openai import OpenAI
import os
from dotenv import load_dotenv

# Get configuration settings
load_dotenv()

# Initialize the OpenAI client
@st.cache_resource
def get_openai_client():
    return OpenAI(
        base_url="https://"+os.getenv("FOUNDRY_PROJECT_RESOURCE")+".openai.azure.com/openai/v1/",
        api_key=os.getenv("FOUNDRY_PROJECT_API_KEY")
    )

def main():
    st.title("AI Chatbot")
    st.caption("Powered by OpenAI")

    # Initialize chat history
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Display chat messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Chat input
    if prompt := st.chat_input("Enter your message"):
        # Add user message to chat history
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Get AI response
        with st.chat_message("assistant"):
            try:
                openai_client = get_openai_client()
                model_deployment = os.getenv("FOUNDTRY_PROJECT_DEPLOYMENT")

                # Prepare messages for API
                api_messages = [
                    {
                        "role": "system",
                        "content": "You are a helpful AI assistant that answers questions and provides information."
                    }
                ]
                api_messages.extend(st.session_state.messages)

                # Get response
                completion = openai_client.chat.completions.create(
                    model=model_deployment,
                    messages=api_messages
                )

                response = completion.choices[0].message.content
                st.markdown(response)

                # Add assistant response to chat history
                st.session_state.messages.append({"role": "assistant", "content": response})

            except Exception as ex:
                st.error(f"Error: {ex}")

if __name__ == '__main__':
    main()
