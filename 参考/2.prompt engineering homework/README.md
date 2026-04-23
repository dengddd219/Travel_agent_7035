# Prompt Engineering Homework - Resume Editing Practice

## Course Information

- **Course**: MSBA7035 - AI Engineering Practice
- **Assignment**: #1
- **Topic**: Resume Optimization using Prompt Engineering Techniques

## Homework Overview

This project demonstrates how to apply various **Prompt Engineering** techniques to automatically edit and optimize resumes. Using Azure OpenAI API (GPT models) as the underlying technology, the project implements four different prompting strategies and evaluates their effectiveness through comparative experiments.

## Technical Architecture

### Core Modules

| File | Description |
|------|-------------|
| [azure_openai_client.py](azure_openai_client.py) | Azure OpenAI API client wrapper with multi-model support, token usage tracking, and content filtering |
| [resume_editor.py](resume_editor.py) | Three basic prompting methods |
| [resume_editor_cot.py](resume_editor_cot.py) | CoT (Chain of Thought) method |
| [evaluation.py](evaluation.py) | LLM-based comparison of four revised resumes; writes `evaluation_report.md` |

### Prompt Engineering Methods

1. **Baseline (Zero-shot)** 
   - Simple edit instruction without examples
   - Result: Average quality, risk of over-generalization

2. **Structured (Few-shot)**
   - Provides STAR format examples
   - Uses strong action verbs, quantified achievements
   - Result: Significantly improved structure

3. **Job-Alignment**
   - Takes job description (JD) as input
   - Extracts keywords and skill requirements
   - Result: Much higher relevance

4. **CoT (Chain of Thought)**
   - Requires model to reason before output
   - Matches CV evidence to JD requirements first
   - Result: Fewer hallucinations, more trustworthy

## Evaluation (`evaluation.py`)

The script uses the same Azure OpenAI client to **compare all four edited versions** against `cv.md` and `jd.md`. It calls `compare_all_methods()` (not per-file `evaluate_resume()` in the default `main` flow).

### Inputs (must exist before running)

| File | Role |
|------|------|
| `cv.md` | Original resume |
| `jd.md` | Target job description |
| `revised_cv_baseline.md` | Baseline (zero-shot) output |
| `revised_cv_structured.md` | Few-shot / structured output |
| `revised_cv_job_alignment.md` | Job-alignment output |
| `revised_cv_cot.md` | CoT output |

Generate the four `revised_cv_*.md` files by running `resume_editor.py` and `resume_editor_cot.py` first.

### Scoring dimensions (rubric passed to the evaluator model)

1. **Clarity and Conciseness** (1–5)  
2. **Professional Tone** (1–5)  
3. **Job Relevance** (1–5)  
4. **Bullet Point Quality** (1–5)  
5. **Overall Readability** (1–5)  
6. **Exaggeration Detection** (−5 to 0; 0 = none, −5 = severe)

The prompt asks for a **total out of 25** on the five positive dimensions, with exaggeration handled as a separate penalty. The module also defines `evaluate_resume(original_cv, edited_cv, job_description)` for **single** original vs. edited evaluation if you call it from your own code.

### Output

- Prints the full comparison to the console.  
- Overwrites **[evaluation_report.md](evaluation_report.md)** with the same text.

## Experimental Results (illustrative)

| Method | Score | Strengths | Weaknesses |
|--------|-------|----------|-----------|
| Baseline | ~15/25 | Simple & fast | Lacks structure |
| Structured | ~18/25 | Well-formatted | Not job-specific |
| Job-Alignment | ~20/25 | High relevance | May over-match |
| CoT | ~19/25 | Transparent reasoning | Longer process |

Scores are indicative; actual judgments follow the rubric above and are saved in [evaluation_report.md](evaluation_report.md) after you run `evaluation.py`.

## Quick Start

### Environment Setup

```bash
# 1. Clone or download this project
# 2. Configure environment variables (.env file)
AZURE_OPENAI_ENDPOINT=your_endpoint
AZURE_OPENAI_API_KEY=your_api_key
AZURE_OPENAI_API_VERSION=2025-01-01-preview
AZURE_OPENAI_DEPLOYMENT=gpt-4.1-mini
```

### Run Experiments

```bash
# Run Methods 1-3
python resume_editor.py

# Run CoT method
python resume_editor_cot.py

# Run evaluation (requires revised_cv_*.md from the steps above)
python evaluation.py
# → prints comparison and writes evaluation_report.md
```

## Key Learning Points

- **Few-shot Learning**: Guide model output through examples
- **Chain of Thought**: Explicit reasoning to reduce hallucinations
- **Role Prompting**: Set professional roles to improve quality
- **Structured Output**: Specify output format for usability
- **Job Alignment**: Optimize content for target position

## File Structure

```
.
├── azure_openai_client.py    # API client
├── resume_editor.py        # Basic methods (3)
├── resume_editor_cot.py   # CoT method
├── evaluation.py           # Evaluation script
├── cv.md                  # Original resume
├── jd.md                 # Job description
├── revised_cv_baseline.md
├── revised_cv_structured.md
├── revised_cv_job_alignment.md
├── revised_cv_cot.md      # Outputs from resume_editor / resume_editor_cot
└── evaluation_report.md  # Evaluation report
```

## Dependencies

- Python 3.8+
- openai library
- python-dotenv

---

**Contact**: For questions, please contact the teaching assistant via course channels