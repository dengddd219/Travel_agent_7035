import json
import time
import tiktoken
import numpy as np
from collections import defaultdict
import pandas as pd
from azure_openai_client import AzureOpenAIClient
from sklearn.metrics import classification_report, accuracy_score, hamming_loss, zero_one_loss, multilabel_confusion_matrix

# generate training_set.jsonl and validation_set.jsonl
#{"messages": [{"role": "system", "content": "Analyze the following service text (title + description) and determine if the service covers each of the three stages of the writing process: Planning, Translating, and Editing."}, {"role": "user", "content": "Title: {title}\nDescription: {description}"}, {"role": "assistant", "content": "{"Planning": 1, "Translating": 0, "Editing": 1}"}]}
def generate_training_validation_sets():
    # read from ft_train_validation.xlsx
    df = pd.read_excel("./data/ft_train_validation.xlsx")
    # shuffle the rows
    df = df.sample(frac=1).reset_index(drop=True)
    # service_name, description are the two columns we are interested in, Planning_4o, Translating_4o, Editing_4o are the three columns we want to predict
    # do a for loop over the rows of the dataframe, for each row, create a line following the example above
    # write the lines to training_set.jsonl and validation_set.jsonl by randomly splitting the lines into two sets by 7:1
    # make sure to close the files after writing
    training_set = []
    validation_set = []
    for i in range(len(df)):
        title = df.loc[i, 'service_name']
        description = df.loc[i, 'description']
        Planning = df.loc[i, 'Planning_4o']
        Translating = df.loc[i, 'Translating_4o']
        Editing = df.loc[i, 'Editing_4o']
        message = {
            "messages": [
                {"role": "system", "content": "Analyze the following service text (title + description) and determine if the service covers each of the three stages of the writing process: Planning, Translating, and Editing."},
                {"role": "user", "content": f"Title: {title}\nDescription: {description}"},
                {"role": "assistant", "content": f'{{"Planning": {Planning}, "Translating": {Translating}, "Editing": {Editing}}}'}
            ]
        }
        if i % 8 == 0:
            validation_set.append(message)
        else:
            training_set.append(message)

    with open('./data/training_set.jsonl', 'w', encoding='utf-8') as f:
        for item in training_set:
            f.write(json.dumps(item) + '\n')
    with open('./data/validation_set.jsonl', 'w', encoding='utf-8') as f:
        for item in validation_set:
            f.write(json.dumps(item) + '\n')

    print("Generated training_set.jsonl and validation_set.jsonl")


# Run preliminary checks
def preliminary_check():
    # Load the training set
    with open('./data/training_set.jsonl', 'r', encoding='utf-8') as f:
        training_dataset = [json.loads(line) for line in f]

    # Training dataset stats
    print("Number of examples in training set:", len(training_dataset))
    print("First example in training set:")
    for message in training_dataset[0]["messages"]:
        print(message)

    # Load the validation set
    with open('./data/validation_set.jsonl', 'r', encoding='utf-8') as f:
        validation_dataset = [json.loads(line) for line in f]

    # Validation dataset stats
    print("\nNumber of examples in validation set:", len(validation_dataset))
    print("First example in validation set:")
    for message in validation_dataset[0]["messages"]:
        print(message)


def num_tokens_from_messages(messages, tokens_per_message=3, tokens_per_name=1):
    encoding = tiktoken.get_encoding(
        "cl100k_base")  # default encoding for gpt-4o models. This requires the latest version of tiktoken to be installed.
    num_tokens = 0
    for message in messages:
        num_tokens += tokens_per_message
        for key, value in message.items():
            num_tokens += len(encoding.encode(value))
            if key == "name":
                num_tokens += tokens_per_name
    num_tokens += 3
    return num_tokens

def num_assistant_tokens_from_messages(messages):
    encoding = tiktoken.get_encoding(
        "cl100k_base")  # default encoding for gpt-4o models. This requires the latest version of tiktoken to be installed.

    num_tokens = 0
    for message in messages:
        if message["role"] == "assistant":
            num_tokens += len(encoding.encode(message["content"]))
    return num_tokens

def print_distribution(values, name):
    print(f"\n#### Distribution of {name}:")
    print(f"min / max: {min(values)}, {max(values)}")
    print(f"mean / median: {np.mean(values)}, {np.median(values)}")
    print(f"p5 / p95: {np.quantile(values, 0.1)}, {np.quantile(values, 0.9)}")

# Validate token counts
def validate_token_counts():
    files = ['training_set.jsonl', 'validation_set.jsonl']

    for file in files:
        print(f"Processing file: {file}")
        with open('./data/'+file, 'r', encoding='utf-8') as f:
            dataset = [json.loads(line) for line in f]

        total_tokens = []
        assistant_tokens = []

        for ex in dataset:
            messages = ex.get("messages", {})
            total_tokens.append(num_tokens_from_messages(messages))
            assistant_tokens.append(num_assistant_tokens_from_messages(messages))

        print_distribution(total_tokens, "total tokens")
        print_distribution(assistant_tokens, "assistant tokens")
        print('*' * 50)

def classify(title, description):
    client = AzureOpenAIClient()
    # GPT-4o-mini prompt (Including more guidance to boost performance)
    prompt = f"""
        Analyze the following service text (title + description) and determine if the service covers each of the three stages of the writing process: Planning, Translating, and Editing.
        For each stage, provide a binary output (1 for yes, 0 for no). No need to explain yourself. No need to repeat the input text or the definitions of the stages. Simply reply in JSON format, e.g., {{"Planning": 1, "Translating": 0, "Editing": 1}}.
        Definitions:
        Planning: This stage involves the initial organization, brainstorming, and outlining of ideas. It includes tasks such as idea generation, information gathering, and data collection.
        Translating: This stage focuses on expressing ideas and translating them into written form. Tasks within this stage may involve storytelling, writing drafts, and more.
        Editing: The editing stage is dedicated to revising and refining written content for clarity, coherence, and correctness.
        Service Text:
        Title: {title}
        Description: {description}
        """
    messages=[{"role": "user", "content": prompt}]

    # GPT-4o-mini fine-tuned model
    # messages = [
    #     {"role": "system",
    #      "content": "Analyze the following service text (title + description) and determine if the service covers each of the three stages of the writing process: Planning, Translating, and Editing."},
    #     {"role": "user", "content": f"Title: {title}\nDescription: {description}"}]
    client.set_deployment_name("gpt-4o-mini")
    # client.set_deployment_name("gpt-4o-mini-ft")
    response = client.get_response(messages)
    print(response.choices[0].message.content)
    print(client.get_token_usage(response))
    return response.choices[0].message.content, client.get_token_usage(response)

def extract_classification(response):
    # extract the classification for each stage
    # response = "{\"  \"Planning\": 0, \"Translating\": 1, \"Editing\": 0}"
    # Find the JSON part in the response
    json_start = response.find("{")
    json_end = response.rfind("}") + 1
    json_str = response[json_start:json_end]

    # Parse the JSON string
    classification = json.loads(json_str)
    return classification

def classify_file(file_path):
    df = pd.read_excel(file_path)
    for i in range(len(df)):
        title = df.loc[i, 'service_name']
        description = df.loc[i, 'description']
        df.loc[i, 'GPTResponse'], token_usage = classify(title, description)
        # extract the classification for each stage
        classification = extract_classification(df.loc[i, 'GPTResponse'])
        df.loc[i, 'Planning'] = classification['Planning']
        df.loc[i, 'Translating'] = classification['Translating']
        df.loc[i, 'Editing'] = classification['Editing']
        # store token usage in the dataframe
        df.loc[i, 'prompt_tokens'] = token_usage['prompt_tokens']
        df.loc[i, 'completion_tokens'] = token_usage['completion_tokens']
        df.loc[i, 'total_tokens'] = token_usage['total_tokens']
        df.loc[i, 'cost'] = token_usage['cost']
        df.to_excel(file_path.replace('.xlsx', '_gpt-4o-mini.xlsx'), index=False)
        print(f"Classification for record {i + 1} completed:", classification)
        time.sleep(60) # for debugging

# Evaluate the multilabel classification performance
def multi_label_eval(file_path):
    # Load the uploaded Excel file
    df = pd.read_excel(file_path)

    # Extract ground truth and predicted values for the three labels
    labels = ['Planning', 'Translating', 'Editing']
    y_true = df[[label + '_4o' for label in labels]]
    y_pred = df[labels]

    # Drop rows with NaN values
    y_true = y_true.dropna()
    y_pred = y_pred.dropna()

    # Ensure the indices match after dropping NaNs
    y_true = y_true.loc[y_pred.index]
    y_pred = y_pred.loc[y_true.index]

    # Calculate classification report for each label
    report = classification_report(y_true, y_pred, target_names=labels)
    print("Classification Report:\n")
    print(report)

    # Calculate accuracy for each label
    accuracy = accuracy_score(y_true, y_pred)
    print(f"Overall Accuracy: {accuracy:.4f}\n")

    # Calculate Hamming Loss
    hamming = hamming_loss(y_true, y_pred)
    print(f"Hamming Loss: {hamming:.4f}\n")

    # Calculate Subset Accuracy (Exact Match Ratio)
    exact_match_ratio = 1 - zero_one_loss(y_true, y_pred)
    print(f"Subset Accuracy (Exact Match Ratio): {exact_match_ratio:.4f}\n")

    # Calculate Multilabel Confusion Matrix
    conf_matrix = multilabel_confusion_matrix(y_true, y_pred)

    # Organize confusion matrix data into a dictionary for better readability
    conf_matrix_dict = {
        label: conf_matrix[i] for i, label in enumerate(labels)
    }

    # Display the multilabel confusion matrix for each label
    print("Multilabel Confusion Matrix:")
    for label, matrix in conf_matrix_dict.items():
        print(f"\nLabel: {label}")
        print(matrix)

if __name__ == "__main__":
    generate_training_validation_sets()
    preliminary_check()
    validate_token_counts()
    # classify_file("./data/ft_evaluation.xlsx")
    multi_label_eval("./data/ft_evaluation_gpt-4o-mini.xlsx")
    multi_label_eval("./data/ft_evaluation_gpt-4o-mini-ft.xlsx")
