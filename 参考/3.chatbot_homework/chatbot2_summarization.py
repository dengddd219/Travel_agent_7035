from azure_openai_client import AzureOpenAIClient
import tiktoken


def _encoding_for_model(model):
    """Return the best available tokenizer for a model/deployment name."""
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        # Azure deployment names may not map directly; choose a close fallback.
        if any(name in model for name in ("gpt-4o", "gpt-4.1", "gpt-5", "gpt-4o-mini", "gpt-4.1-mini", "gpt-5-mini")):
            return tiktoken.get_encoding("o200k_base")
        return tiktoken.get_encoding("cl100k_base")


def count_tokens(text, model="gpt-4.1-mini"):
    """Count tokens for plain text."""
    tokenizer = _encoding_for_model(model)
    return len(tokenizer.encode(text))


def _count_content_tokens(content, tokenizer):
    """Count tokens for message content; supports string or multimodal list payloads."""
    if isinstance(content, str):
        return len(tokenizer.encode(content))
    if isinstance(content, list):
        total = 0
        for part in content:
            if isinstance(part, dict):
                # Count text-like fields only; image payloads don't map cleanly to text tokenizers.
                if "text" in part and isinstance(part["text"], str):
                    total += len(tokenizer.encode(part["text"]))
                elif "type" in part:
                    total += len(tokenizer.encode(str(part["type"])))
            else:
                total += len(tokenizer.encode(str(part)))
        return total
    return len(tokenizer.encode(str(content)))


def count_chat_tokens(messages, model="gpt-4.1-mini"):
    """Estimate chat prompt tokens using OpenAI chat message framing rules."""
    tokenizer = _encoding_for_model(model)
    # Most current chat models use this framing; good practical estimate for Azure chat deployments.
    tokens_per_message = 3
    tokens_per_name = 1

    total = 0
    for message in messages:
        total += tokens_per_message
        for key, value in message.items():
            if key == "content":
                total += _count_content_tokens(value, tokenizer)
            else:
                total += len(tokenizer.encode(str(value)))
            if key == "name":
                total += tokens_per_name

    # Assistant priming: every chat reply is primed with extra tokens.
    total += 3
    return total

# write a function to check if the messages exceed a token limit
def check_token_limit(messages, token_limit=600, model="gpt-4.1-mini"):  # 600 is low; used for quick testing.
    """Check whether estimated prompt tokens exceed the configured prompt budget."""
    prompt_tokens = count_chat_tokens(messages, model=model)
    return prompt_tokens > token_limit


# ========== MODIFICATION 1: Replaced remove_oldest_messages with summarize_old_messages ==========
# Original function (now replaced):
# def remove_oldest_messages(messages, token_limit=600, model="gpt-4.1-mini"):
#     """Trim oldest conversation turns (after system message) until prompt budget is met."""
#     # Keep index 0 system instruction if present.
#     while len(messages) > 1 and count_chat_tokens(messages, model=model) > token_limit:
#         # Prefer removing a full oldest turn to preserve coherent context.
#         if len(messages) > 2 and messages[1].get("role") == "user" and messages[2].get("role") == "assistant":
#             messages.pop(1)
#             messages.pop(1)
#         else:
#             messages.pop(1)
#     return messages

# New function (summarization-based):
def summarize_old_messages(messages, client, model="gpt-4.1-mini"):
    """Summarize older conversation turns to compress context while preserving key information."""
    if len(messages) <= 2:  # Only system + current turn, nothing to summarize
        return messages

    # Keep system message (index 0) and recent messages (last 2-4 turns)
    system_msg = messages[0] if messages[0].get("role") == "system" else None
    recent_count = 4  # Keep last 4 messages (2 user-assistant turns)

    if len(messages) <= recent_count + (1 if system_msg else 0):
        return messages

    # Messages to summarize: everything between system and recent messages
    start_idx = 1 if system_msg else 0
    end_idx = len(messages) - recent_count
    messages_to_summarize = messages[start_idx:end_idx]

    # Build conversation text for summarization
    conversation_text = "\n".join([
        f"{msg['role']}: {msg['content']}"
        for msg in messages_to_summarize
    ])

    # Request summary from API
    summary_prompt = [
        {"role": "system", "content": "You are a conversation summarizer. Create a concise summary of the conversation history that preserves key technical details, decisions, and context."},
        {"role": "user", "content": f"Summarize this conversation concisely:\n\n{conversation_text}"}
    ]

    print("\n[Summarizing older messages to save context...]")
    response = client.get_response(summary_prompt)
    summary = response.choices[0].message.content

    # Build new message list: system + summary + recent messages
    new_messages = []
    if system_msg:
        new_messages.append(system_msg)

    new_messages.append({
        "role": "system",
        "content": f"Previous conversation summary: {summary}"
    })

    new_messages.extend(messages[end_idx:])

    return new_messages


def print_message_previews(messages, preview_chars=80):
    """Print the beginning of each message to inspect prompt content."""
    print("\n##########\nPrompt preview sent to API:")
    for i, message in enumerate(messages, start=1):
        role = message.get("role", "unknown")
        content = str(message.get("content", "")).replace("\n", "\\n")
        preview = content[:preview_chars]
        if len(content) > preview_chars:
            preview += "..."
        print(f"{i:02d}. [{role}] {preview}")
    print("##########\n")

def chatbot():
    client = AzureOpenAIClient()
    model_name = client.get_deployment_name() or "gpt-4.1-mini"
    messages = []
    # add a system message to define the bot behavior
    # Technical Support Bot
    messages.append({"role": "system",
                     "content": "You are a technical support bot. Provide clear and concise technical assistance."})
    # Casual and Fun Chatbot
    # messages.append({"role": "system",
    #                  "content": "You are a casual and fun chatbot. Engage the user with humor and light-hearted conversation while still providing useful information."})
    print("Welcome to the chatbot!")
    prompt_token_limit = 600

    while True:
        user_input = input("You: ")
        if user_input.lower() == "exit":
            break
        messages.append({"role": "user", "content": user_input})
        # ========== MODIFICATION 2: Use summarization instead of deletion ==========
        # Original code:
        # if check_token_limit(messages, token_limit=prompt_token_limit, model=model_name):
        #     messages = remove_oldest_messages(messages, token_limit=prompt_token_limit, model=model_name)

        # New code (summarization-based):
        if check_token_limit(messages, token_limit=prompt_token_limit, model=model_name):
            messages = summarize_old_messages(messages, client, model=model_name)

        # before sending to API, print an excerpt of the messages
        print_message_previews(messages)
        estimated_prompt_tokens = count_chat_tokens(messages, model=model_name)
        print(f"Estimated prompt tokens (pre-request): {estimated_prompt_tokens}")
        response = client.get_response(messages)
        bot_response = response.choices[0].message.content
        # add bot response to the conversation history
        messages.append({"role": "assistant", "content": bot_response})
        # Also keep history in-budget right after appending the assistant answer.
        if check_token_limit(messages, token_limit=prompt_token_limit, model=model_name):
            messages = summarize_old_messages(messages, client, model=model_name)
        print(f"Bot: {bot_response}")
        # print token usage
        token_usage = client.get_token_usage(response.to_dict())

        print(
            "Actual token usage: "
            f"prompt={token_usage['prompt_tokens']}, "
            f"completion={token_usage['completion_tokens']}, "
            f"total={token_usage['total_tokens']}, "
            f"cost={token_usage['cost_display']}"
        )

if __name__ == "__main__":
    chatbot()

"""
test the chatbot with the following conversation:

hi
why is it so fast for github copilot to generate code suggestions?
are code suggestions done locally or on the server and sent back over Internet?
but is my machine fast enough?
how fast does my internet connection need to be?
exit

"""