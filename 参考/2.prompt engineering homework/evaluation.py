"""
Resume Editor Evaluation - Compare outputs from different prompt designs
"""

from azure_openai_client import AzureOpenAIClient

# Evaluation criteria
EVALUATION_CRITERIA = """
Evaluate the resume based on the following dimensions:
1. Clarity and Conciseness (1-5): How clear and concise is the content?
2. Professional Tone (1-5): Is the tone professional and appropriate?
3. Job Relevance (1-5): How relevant is the content to the target job?
4. Bullet Point Quality (1-5): Are bullet points well-structured with action verbs and impact?
5. Overall Readability (1-5): Is the resume easy to read and navigate?
6. Exaggeration Detection (-5 to 0): Does the content contain exaggerated claims or overstatement? (0 = none, -5 = severe exaggeration)
"""

def evaluate_resume(original_cv, edited_cv, job_description):
    """Evaluate the edited resume against the original."""
    client = AzureOpenAIClient()

    prompt = f"""You are an expert resume evaluator. Compare the original and edited resumes, then evaluate the edited version.

{EVALUATION_CRITERIA}

Original Resume:
{original_cv}

Edited Resume:
{edited_cv}

Target Job Description:
{job_description}

Please provide:
1. Summary of key changes made
2. Evaluation scores for each dimension (1-5, except Exaggeration which is -5 to 0)
3. Overall assessment and recommendations for improvement

Format your response as:
### Changes Made:
[List key changes]

### Scores:
- Clarity and Conciseness: X/5
- Professional Tone: X/5
- Job Relevance: X/5
- Bullet Point Quality: X/5
- Overall Readability: X/5
- Exaggeration Detection: X/-5 (0 = none, -5 = severe)
- Total: X/25 (with exaggeration penalty applied separately)

### Overall Assessment:
[Your assessment]

### Recommendations:
[Any recommendations for further improvement]"""

    messages = [{"role": "user", "content": prompt}]
    response = client.get_response(messages)
    return response.choices[0].message.content


def compare_all_methods(cv_text, jd_text, baseline_cv, structured_cv, job_alignment_cv, cot_cv):
    """Compare all four editing methods."""
    client = AzureOpenAIClient()

    prompt = f"""You are an expert resume evaluator. Compare the four edited resume versions and evaluate which approach is most effective.

{EVALUATION_CRITERIA}

Original Resume:
{cv_text}

Target Job Description:
{jd_text}

=== Method 1: Baseline (Zero-shot) ===
{baseline_cv}

=== Method 2: Few-Shot / Structured ===
{structured_cv}

=== Method 3: Job-Alignment ===
{job_alignment_cv}

=== Method 4: CoT (Chain-of-Thought) ===
{cot_cv}

Please provide a detailed comparison:
1. Strengths and weaknesses of each method
2. Which method produced the best result for this specific job?
3. What prompt elements proved most significant?
4. Recommendations for prompt improvement

Format:
### Method 1 - Baseline:
Strengths: [...]
Weaknesses: [...]

### Method 2 - Structured:
Strengths: [...]
Weaknesses: [...]

### Method 3 - Job-Alignment:
Strengths: [...]
Weaknesses: [...]

### Method 4 - CoT:
Strengths: [...]
Weaknesses: [...]

### Best Method for This Job:
[Which method worked best and why]

### Key Prompt Elements:
[Which prompt elements made the biggest difference]

### Recommendations:
[How would you improve the prompts?]"""

    messages = [{"role": "user", "content": prompt}]
    response = client.get_response(messages)
    return response.choices[0].message.content


if __name__ == "__main__":
    import os

    # Use the same directory as the script
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    CV_PATH = os.path.join(SCRIPT_DIR, 'cv.md')
    JD_PATH = os.path.join(SCRIPT_DIR, 'jd.md')

    def read_file(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()

    cv_text = read_file(CV_PATH)
    jd_text = read_file(JD_PATH)

    # Read edited versions (from same directory)
    with open(os.path.join(SCRIPT_DIR, 'revised_cv_baseline.md'), 'r', encoding='utf-8') as f:
        baseline_cv = f.read()

    with open(os.path.join(SCRIPT_DIR, 'revised_cv_structured.md'), 'r', encoding='utf-8') as f:
        structured_cv = f.read()

    with open(os.path.join(SCRIPT_DIR, 'revised_cv_job_alignment.md'), 'r', encoding='utf-8') as f:
        job_alignment_cv = f.read()

    with open(os.path.join(SCRIPT_DIR, 'revised_cv_cot.md'), 'r', encoding='utf-8') as f:
        cot_cv = f.read()

    print("=" * 60)
    print("Comparing All Methods")
    print("=" * 60)

    comparison_result = compare_all_methods(cv_text, jd_text, baseline_cv, structured_cv, job_alignment_cv, cot_cv)
    print(comparison_result)

    # Save comparison to file
    with open(os.path.join(SCRIPT_DIR, 'evaluation_report.md'), 'w', encoding='utf-8') as f:
        f.write(comparison_result)

    print("\n" + "=" * 60)
    print("Evaluation saved to evaluation_report.md")
    print("=" * 60)