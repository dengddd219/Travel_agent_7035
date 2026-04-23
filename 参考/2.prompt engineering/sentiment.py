from azure_openai_client import AzureOpenAIClient

# use azure openai to do sentiment analysis, show the technique of zero-shot, one-shot, and few-shot prompt engineering
def zero_shot(text):
    client = AzureOpenAIClient()
    prompt = f"""Analyze the sentiment of the following text. The sentiment can be positive, negative, or neutral. 
              Text: {text}"""
    messages=[{"role": "user", "content": prompt}]
    response = client.get_response(messages)
    return response.choices[0].message.content

# test the function
print("Zero-shot prompt engineering")
text = "I love the weather today. It's sunny and warm."
print(zero_shot(text))
text = "I hate the weather today. It's rainy and cold."
print(zero_shot(text))
text = "The weather today is okay. It's cloudy and cool."
print(zero_shot(text))

# one-shot prompt engineering
def one_shot(text):
    client = AzureOpenAIClient()
    # one shot prompt engineering
    prompt = f"""Analyze the sentiment of the following text. The sentiment can be positive, negative, or neutral. 
            Text: I am thrilled with the excellent service I received at the restaurant!
            Sentiment: Positive
            Text: {text}"""
    messages=[{"role": "user", "content": prompt}]
    response = client.get_response(messages)
    return response.choices[0].message.content

# test the function
print("One-shot prompt engineering")
text = "I love the weather today. It's sunny and warm."
print(one_shot(text))
text = "I hate the weather today. It's rainy and cold."
print(one_shot(text))
text = "The weather today is okay. It's cloudy and cool."
print(one_shot(text))

# few-shot prompt engineering
def few_shot(text):
    client = AzureOpenAIClient()
    # few shot prompt engineering
    prompt = f"""Analyze the sentiment of the following text. The sentiment can be positive, negative, or neutral. 
            Text: I am thrilled with the excellent service I received at the restaurant!
            Sentiment: Positive
            Text: I am disappointed with the poor service I received at the restaurant.
            Sentiment: Negative
            Text: {text}"""
    messages=[{"role": "user", "content": prompt}]
    response = client.get_response(messages)
    return response.choices[0].message.content

# test the function
print("Few-shot prompt engineering")
text = "I love the weather today. It's sunny and warm."
print(few_shot(text))
text = "I hate the weather today. It's rainy and cold."
print(few_shot(text))
text = "The weather today is okay. It's cloudy and cool."
print(few_shot(text))


