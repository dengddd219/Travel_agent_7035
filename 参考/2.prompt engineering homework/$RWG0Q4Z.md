# MSBA7035 Individual Assignment 1: AI Resume Editor

**Deadline:** Thursday, April 2, 2026 11:59pm

---

## Introduction

Build an AI-powered resume editor using Azure OpenAI (gpt-4.1-mini) through prompt engineering. Goal: design, test, and refine prompts that help revise and polish resumes for specific job contexts, while maintaining factual accuracy and professional tone.

---

## Task Overview

1. Select or create a resume (your own or a provided sample)
2. Choose a target job description
3. Design prompts that instruct the LLM to revise and polish the resume
4. Compare outputs from different prompt designs
5. Reflect on what prompt elements improve resume quality and why

---

## Input Data

| Item | Description |
|------|-------------|
| **Resume** | Your own (recommended) or a synthetic resume. Do NOT include sensitive personal info (phone number, exact address) |
| **Job Description** | Select one real job posting. Include full job description text and original URL in submission |

---

## Requirements

### 1. Baseline Resume Editing Prompt
Design a basic prompt that asks the LLM to revise and polish the resume.

### 2. Few-Shot or Structured Prompt Version
Design an improved prompt using one or more of these techniques:

- Few-shot examples (before → after bullet points)
- Structured editing rules (e.g., STAR format, action verbs)
- Section-specific instructions (summary, experience, skills)

### 3. Job-Alignment Prompt
Design a prompt that explicitly aligns the resume with the chosen job description.

### 4. Comparison & Evaluation
Compare original and edited versions along multiple dimensions:

- Clarity and conciseness
- Professional tone
- Job relevance
- Bullet point quality (action verbs, impact)
- Overall readability

---

## Deliverables

1. **Python program (.py)** - Include multiple .py files if needed
   - Include `azure_openai_client.py` and `.env` file for API calls
   - Use relative paths for file access

2. **Written report (Word)** - Summarize comparison and evaluation
   - Include reflections on successful aspects, less effective aspects
   - Highlight prompt elements that proved most significant

3. **Zip file** - Compress all files
   - Include: original resume, job description, three edited resumes
   - Name: `{studentID}.zip` (e.g., `123456.zip`)