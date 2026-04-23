import os
import json
from openai import AzureOpenAI
from openai import BadRequestError
from dotenv import load_dotenv
import base64

class AzureOpenAIClient:
    def __init__(self):
        load_dotenv()
        self.client = AzureOpenAI(
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION") # "2025-01-01-preview"
        )
        self.deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT") # gpt-4.1-mini, gpt-4.1, gpt-5-mini, gpt-5
        self.deployment_embedding = os.getenv("AZURE_OPENAI_DEPLOYMENT_EMBEDDING") # text-embedding-3-small, text-embedding-3-large

    def set_deployment_name(self, deployment_name):
        self.deployment_name = deployment_name

    def get_deployment_name(self):
        return self.deployment_name

    # def get_response(self, prompt):
    #     messages = [{"role": "user", "content": prompt}]
    #     try:
    #         response = self.client.chat.completions.create(
    #             model=self.deployment_name,
    #             messages=messages,
    #         )
    #         return response
    #     except BadRequestError as e:
    #         error_message = e.json_body.get('error', {}).get('message', 'An error occurred')
    #         return f"Error: {error_message}"

    def get_response(self, messages):
        # messages = [{"role": "user", "content": prompt}]
        try:
            response = self.client.chat.completions.create(
                model=self.deployment_name,
                messages=messages,
                # you can set additional parameters here such as temperature, max_completion_tokens, etc.
            )
            return response
        except BadRequestError as e:
            error_message = e.json_body.get('error', {}).get('message', 'An error occurred')
            return f"Error: {error_message}"

    def get_response_to_image(self, system_message, user_prompt, image_path):
        try:
            with open(image_path, "rb") as image_file:
                encoded_image = base64.b64encode(image_file.read()).decode('utf-8')

            messages = [
                {"role": "system", "content": system_message},
                {"role": "user", "content": [
                    {
                        "type": "text",
                        "text": user_prompt
                    },
                    {
                        "type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded_image}"}
                    }
                ]}
            ]

            response = self.client.chat.completions.create(
                model=self.deployment_name,
                messages=messages,
            )
            # print(response)
            return response
        except BadRequestError as e:
            # Extract the error message directly from the exception
            error_message = getattr(e, 'message', 'An error occurred')
            print(f"BadRequestError: {error_message}")
            return f"Error: {error_message}"
        except Exception as e:
            # Handle any other unexpected exceptions
            print(f"Unexpected error: {str(e)}")
            return f"Error: {str(e)}"
        # except BadRequestError as e:
        #     # error_message = e.json_body.get('error', {}).get('message', 'An error occurred')
        #     error_message = e.error.get('message', 'An error occurred')
        #     print(f"BadRequestError: {error_message}")
        #     return f"Error: {error_message}"

    def generate_embedding(self, text, dimensions=1536):
        response = self.client.embeddings.create(
            model=self.deployment_embedding,
            input=text,
            dimensions=dimensions
        )
        return response

    @staticmethod
    def _format_usd(amount):
        """Format USD values without scientific notation for UI/log output."""
        formatted = f"{amount:.8f}".rstrip("0").rstrip(".")
        if "." not in formatted:
            formatted = f"{formatted}.00"
        return f"${formatted}"

    def get_token_usage(self, response):
        # print(response)
        # Support both SDK response objects and dict payloads from response.to_dict().
        usage = response.get("usage") if isinstance(response, dict) else getattr(response, "usage", None)
        if usage is None:
            raise ValueError("Response does not contain usage information.")

        completion_tokens = usage.get("completion_tokens", 0) if isinstance(usage, dict) else usage.completion_tokens
        prompt_tokens = usage.get("prompt_tokens", 0) if isinstance(usage, dict) else usage.prompt_tokens
        total_tokens = usage.get("total_tokens", 0) if isinstance(usage, dict) else usage.total_tokens
        cost_per_prompt_token = 2.5/1000000  # cost per prompt token for gpt-4o
        cost_per_completion_token = 10/1000000  # cost per completion token for gpt-4o
        if self.deployment_name == "gpt-4o-mini":
            cost_per_prompt_token = 0.15 / 1000000
            cost_per_completion_token = 0.6 / 1000000
        if self.deployment_name == "gpt-4.1-mini":
            cost_per_prompt_token = 0.4 / 1000000
            cost_per_completion_token = 1.6 / 1000000
        if self.deployment_name == "gpt-4.1":
            cost_per_prompt_token = 2 / 1000000
            cost_per_completion_token = 8 / 1000000
        if self.deployment_name == "gpt-5":
            cost_per_prompt_token = 1.25 / 1000000
            cost_per_completion_token = 10 / 1000000
        if self.deployment_name == "gpt-5-mini":
            cost_per_prompt_token = 0.25 / 1000000
            cost_per_completion_token = 2 / 1000000
        total_cost = (prompt_tokens * cost_per_prompt_token) + (completion_tokens * cost_per_completion_token)
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost": total_cost,
            "cost_display": self._format_usd(total_cost)
        }

    def check_prompt_filter(self, response):
        prompt_filter_results = response.prompt_filter_results[0]["content_filter_results"]
        filtered_categories = [category for category, data in prompt_filter_results.items() if
                               data.get("severity", "safe") != "safe"]
        return filtered_categories

    def check_content_filter(self, response):
        content_filter_results = response.choices[0].content_filter_results
        filtered_categories = [category for category, data in content_filter_results.items() if
                               data.get("severity", "safe") != "safe"]
        return filtered_categories

