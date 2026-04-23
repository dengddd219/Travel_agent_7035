import streamlit as st

from azure_openai_client import AzureOpenAIClient
from chatbot2 import check_token_limit, count_chat_tokens, remove_oldest_messages


SYSTEM_PROMPT = "You are a technical support bot. Provide clear and concise technical assistance."
DEFAULT_PROMPT_TOKEN_LIMIT = 600


def _init_state() -> None:
    if "client" not in st.session_state:
        st.session_state.client = AzureOpenAIClient()
    if "model_name" not in st.session_state:
        st.session_state.model_name = st.session_state.client.get_deployment_name() or "gpt-4.1-mini"
    if "prompt_token_limit" not in st.session_state:
        st.session_state.prompt_token_limit = DEFAULT_PROMPT_TOKEN_LIMIT
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if "last_usage" not in st.session_state:
        st.session_state.last_usage = None


def _reset_chat() -> None:
    st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    st.session_state.last_usage = None


def _extract_assistant_text(response) -> str:
    content = response.choices[0].message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part) for part in content)
    return str(content)


def main() -> None:
    st.set_page_config(page_title="Azure Technical Support Chatbot", page_icon="🤖")
    _init_state()

    st.title("Azure Technical Support Chatbot")
    st.caption("Streamlit UI version of chatbot2.py")

    with st.sidebar:
        st.subheader("Settings")
        st.session_state.prompt_token_limit = st.number_input(
            "Prompt token limit",
            min_value=100,
            max_value=64000,
            value=int(st.session_state.prompt_token_limit),
            step=100,
        )
        st.write(f"Model: `{st.session_state.model_name}`")
        if st.button("Clear chat"):
            _reset_chat()
            st.rerun()

        estimated_prompt_tokens = count_chat_tokens(
            st.session_state.messages,
            model=st.session_state.model_name,
        )
        st.metric("Estimated prompt tokens", estimated_prompt_tokens)

        if st.session_state.last_usage:
            usage = st.session_state.last_usage
            st.subheader("Last API usage")
            st.write(
                f"prompt={usage['prompt_tokens']}, completion={usage['completion_tokens']}, "
                f"total={usage['total_tokens']}, cost={usage['cost_display']}"
            )

    for message in st.session_state.messages:
        role = message.get("role", "assistant")
        if role == "system":
            continue
        with st.chat_message(role):
            st.write(message.get("content", ""))

    user_input = st.chat_input("Ask a technical support question...")
    if not user_input:
        return

    st.session_state.messages.append({"role": "user", "content": user_input})

    if check_token_limit(
        st.session_state.messages,
        token_limit=int(st.session_state.prompt_token_limit),
        model=st.session_state.model_name,
    ):
        st.session_state.messages = remove_oldest_messages(
            st.session_state.messages,
            token_limit=int(st.session_state.prompt_token_limit),
            model=st.session_state.model_name,
        )

    with st.chat_message("user"):
        st.write(user_input)

    with st.chat_message("assistant"):
        response = st.session_state.client.get_response(st.session_state.messages)

        if isinstance(response, str):
            bot_response = response
            st.session_state.last_usage = None
        else:
            bot_response = _extract_assistant_text(response)
            try:
                st.session_state.last_usage = st.session_state.client.get_token_usage(response.to_dict())
            except Exception:
                st.session_state.last_usage = None

        st.write(bot_response)

    st.session_state.messages.append({"role": "assistant", "content": bot_response})
    st.session_state.messages = remove_oldest_messages(
        st.session_state.messages,
        token_limit=int(st.session_state.prompt_token_limit),
        model=st.session_state.model_name,
    )


if __name__ == "__main__":
    main()

