---
name: icd10-clinical-extraction
description: Use when extracting coding-relevant clinical facts from inpatient documentation to ensure accurate ICD-10 coding.
---

# icd10-clinical-extraction

## Purpose
Extract documented clinical facts accurately. Focus on facts that directly impact ICD-10-CM and ICD-10-PCS code assignment. 

## Workflow & Tool Usage
1. **Execute Extraction**: Run `medspacy_extract_clinical_context` on the raw clinical note.
2. **Analyze**: Use `think_tool` to review the JSON. Identify the principal diagnosis, significant procedures, and flag missing context (laterality, POA status).
3. **Compile**: Draft the final extraction summary following the Exact Output Template.

## Coding Alignment Rules
- **Strict Documentation**: Extract ONLY what is explicitly documented. Do not infer or upgrade specificity.
- **Traceability**: Every extracted fact must be directly traceable to the raw clinical note.
- **ICD-10 Requirements**: Specifically capture laterality, acuity, root operations, etiology/manifestation relationships, and POA indicators.

## Exact Output Template
Your final response must strictly follow this markdown structure:

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

### 4. Documentation Gaps
* [List missing details, e.g., "Laterality not specified for humerus fracture"]
* [If none, write "None"]

## STRICT Constraints
- **NO CODES**: Do NOT assign or suggest any ICD-10-CM or ICD-10-PCS codes. You are an extractor, not the coder.
- **NO INVENTIONS**: Do not assume relationships not explicitly written.
- **NO LOGS**: Do not include `think_tool` logs or JSON in the final output.