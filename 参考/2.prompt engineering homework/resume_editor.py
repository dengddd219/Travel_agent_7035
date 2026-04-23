"""
AI Resume Editor - MSBA7035 Individual Assignment 1
Using prompt engineering to revise and polish resumes for specific job contexts.
"""

from azure_openai_client import AzureOpenAIClient
import os

# Read CV and JD from files
def read_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()

CV_PATH = os.path.join(os.path.dirname(__file__), 'cv.md')
JD_PATH = os.path.join(os.path.dirname(__file__), 'jd.md')

# Method 1: Baseline Resume Editing Prompt (Zero-shot)

def baseline_edit(cv_text):
    """Basic prompt that asks the LLM to revise and polish the resume."""
    client = AzureOpenAIClient()
    prompt = f"""You are a professional resume editor. Please revise and polish the following resume to make it more professional, concise, and impactful. Improve the clarity, tone, and readability of the content.

Resume:
{cv_text}

Please provide the revised resume."""

    messages = [{"role": "user", "content": prompt}]
    response = client.get_response(messages)
    return response.choices[0].message.content



# Method 2: Few-Shot / Structured Prompt

def structured_edit(cv_text):
    """
    Improved prompt using few-shot examples and structured editing rules.
    Uses STAR format and action verbs.
    """
    client = AzureOpenAIClient()

    prompt = f"""You are a professional resume editor. Please revise and polish the following resume using the following structured rules:

1. Use strong action verbs at the beginning of each bullet point (e.g., Developed, Led, Implemented, Analyzed, Designed, Built)
2. Use STAR format: Situation, Task, Action, Result
3. Quantify achievements where possible (numbers, percentages, metrics)
4. Keep bullet points concise (1-2 lines max)
5. Maintain factual accuracy - do not invent information

Example transformation:
Original: "I helped with data analysis using Python."
Revised: "• Analyzed large datasets using Python, extracting actionable insights for stakeholder decisions."

Original: "I worked on a project with team members."
Revised: "• Collaborated with cross-functional teams to deliver projects on time and within budget."

Now revise this resume:
{cv_text}

Please provide the revised resume following these rules."""

    messages = [{"role": "user", "content": prompt}]
    response = client.get_response(messages)
    return response.choices[0].message.content



# Method 3: Job-Alignment Prompt

def job_alignment_edit(cv_text, job_description):
    """
    Prompt that explicitly aligns the resume with the job description.
    Emphasizes relevant skills and experiences.
    """
    client = AzureOpenAIClient()

    prompt = f"""You are a professional resume editor and career advisor. Your task is to tailor the resume to match the target job description.

Target Job Description:
{job_description}

Instructions:
1. Highlight skills and experiences that are most relevant to the job requirements
2. Use terminology and keywords from the job description
3. Reorder and emphasize content that matches job requirements
4. Keep achievements and experiences that directly support the application
5. Maintain factual accuracy - do not invent information
6. Maintain professional tone and quantify impact where possible

Resume:
{cv_text}

Please provide the revised, job-aligned resume."""

    messages = [{"role": "user", "content": prompt}]
    response = client.get_response(messages)
    return response.choices[0].message.content



# Main - Test all three methods

if __name__ == "__main__":
    # Read CV and JD
    cv_text = read_file(CV_PATH)
    jd_text = read_file(JD_PATH)

    print("=" * 60)
    print("Method 1: Baseline Resume Editing (Zero-shot)")
    print("=" * 60)
    baseline_result = baseline_edit(cv_text)
    print(baseline_result)

    # Save to file (in same directory)
    with open('revised_cv_baseline.md', 'w', encoding='utf-8') as f:
        f.write(baseline_result)

    print("\n" + "=" * 60)
    print("Method 2: Few-Shot / Structured Prompt")
    print("=" * 60)
    structured_result = structured_edit(cv_text)
    print(structured_result)

    with open('revised_cv_structured.md', 'w', encoding='utf-8') as f:
        f.write(structured_result)

    print("\n" + "=" * 60)
    print("Method 3: Job-Alignment Prompt")
    print("=" * 60)
    job_alignment_result = job_alignment_edit(cv_text, jd_text)
    print(job_alignment_result)

    with open('revised_cv_job_alignment.md', 'w', encoding='utf-8') as f:
        f.write(job_alignment_result)

    print("\n" + "=" * 60)
    print("All results saved to files!")
    print("=" * 60)