---
name: icd10-clinical-extraction
description: Use when extracting coding-relevant clinical facts from inpatient documentation to ensure accurate ICD-10 coding.
---

# icd10-clinical-extraction

## Purpose
Extract documented clinical facts accurately. Focus on facts that directly impact ICD-10-CM and ICD-10-PCS code assignment. Keep it simple, accurate, and perfectly formatted for the downstream coding agent.

## Workflow & Tool Usage
1. **Execute Extraction**: You MUST run `medspacy_extract_clinical_context` on the raw clinical note first.
2. **Analyze**: Use `think_tool` to review the returned JSON. Identify the principal diagnosis, significant procedures, and flag any missing context (like laterality or POA status).
3. **Compile**: Draft the final extraction summary following the Exact Output Template below.

## Coding Alignment Rules
- Extract ONLY what is explicitly documented. Do not infer, assume, or upgrade specificity beyond documentation.
- Capture the provider's exact clinical wording when it clarifies coding intent.
- Ensure every extracted fact is directly traceable to the raw clinical note.
- Align extraction with ICD-10-CM/PCS requirements: capture laterality, acuity, root operations, etiology/manifestation relationships, and POA indicators.

## Exact Output Template
Your final response must strictly follow this markdown structure. Do not deviate.

### 1. Diagnoses
* **Principal Candidate:** [Condition] (Acuity: [X], POA: [Yes/No/Unclear])
* **Additional/Secondary:** 
  * [Condition] (Acuity: [X], POA: [X])
* **Historical/Ruled Out:** [List any relevant conditions]

### 2. Procedures
* **Primary Candidate:** [Procedure name] 
  * Details: [Body Part], [Approach], [Device/Qualifier if explicitly stated]
* **Secondary Procedures:** [List others]

### 3. Key Clinical Context & Linkages
* [e.g., "Provider explicitly linked Sepsis as 'due to' Pneumonia"]
* [e.g., "Patient is right-hand dominant"]

### 4. Documentation Gaps
* [List any missing details that will prevent highly specific coding, e.g., "Laterality not specified for humerus fracture"]
* [If none, write "None"]

## STRICT Do Not Do
- **CRITICAL:** Do NOT assign or suggest any ICD-10-CM or ICD-10-PCS codes in this step. You are an extractor, not the coder.
- Do not invent clinical facts, symptoms, or assume relationships not explicitly written.
- Do not include `think_tool` logs or JSON data in your final output template.