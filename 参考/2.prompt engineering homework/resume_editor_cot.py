"""
AI Resume Editor - CoT (Chain of Thought) Version
Using chain-of-thought reasoning to polish resumes
"""

from azure_openai_client import AzureOpenAIClient
import os

# Read CV and JD from files
def read_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()

CV_PATH = os.path.join(os.path.dirname(__file__), 'cv.md')
JD_PATH = os.path.join(os.path.dirname(__file__), 'jd.md')


# CoT Method: Chain of Thought Resume Polishing

def cot_edit(cv_text, job_description):
    """
    Use Chain of Thought (CoT) method to polish resume
    Steps:
    1. Extract core requirements from JD
    2. Find evidence in CV that proves the capability
    3. If no evidence, output 'No match' and exclude from final resume
    4. If there's evidence, explain how to polish it to be more product-oriented
    5. Only generate final resume text after completing this reasoning process
    """
    client = AzureOpenAIClient()

    prompt = f"""Before rewriting my resume, please complete the following mapping/reasoning process:

1. Extract the core requirements from the JD.
2. Find specific sentences in my original CV that prove I have that capability.
3. If there's no evidence in my CV, output 'No match' and do NOT include it in the final resume.
4. If there's evidence, explain how you plan to polish it to be more product-oriented without exaggerating the technical scope.
5. Only generate the final resume text AFTER completing this reasoning process.

Please output in the following format:

=== Chain of Thought Reasoning ===
【Core Requirement 1】: XXX
  CV Match Evidence: XXX (specific sentence) or No match
  Polishing Rationale: XXX

【Core Requirement 2】: XXX
  CV Match Evidence: XXX (specific sentence) or No match
  Polishing Rationale: XXX

... (continue for all core requirements)

=== Final Polished Resume ===
[Generate complete resume text here]

========== Raw Materials Below ==========

Target Job Description:
{job_description}

My Original Resume:
{cv_text}

========== Start Reasoning =========="""

    messages = [{"role": "user", "content": prompt}]
    response = client.get_response(messages)
    return response.choices[0].message.content


# Main - Test CoT method

if __name__ == "__main__":
    # Use the same directory as the script
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

    # Read CV and JD
    cv_text = read_file(CV_PATH)
    jd_text = read_file(JD_PATH)

    print("=" * 60)
    print("CoT (Chain of Thought) Resume Polishing")
    print("=" * 60)
    cot_result = cot_edit(cv_text, jd_text)
    print(cot_result)

    # Save to file (in same directory)
    with open(os.path.join(SCRIPT_DIR, 'revised_cv_cot.md'), 'w', encoding='utf-8') as f:
        f.write(cot_result)

    print("\n" + "=" * 60)
    print("Result saved to revised_cv_cot.md")
    print("=" * 60)