---
name: icd10-cm-diagnosis
description: INVOKE THIS SKILL when assigning ICD-10-CM diagnosis codes based on the clinical extraction summary. Guides code selection via RAG tools, guideline application, and specificity validation.
---

# icd10-cm-diagnosis

## Overview
This skill provides a structured workflow to accurately assign **ICD-10-CM diagnosis codes**. It emphasizes the *Official Guidelines for Coding and Reporting* and clinical validation principles. 
**Golden Rule**: Code only what is documented in the extraction summary. Never assume or infer.

## Step 1: Consume Extraction & Confirm Encounter Rules
Review the extraction summary provided by the previous agent. Identify the encounter type to apply the correct logic:
*   **Inpatient**: Code confirmed + "probable/suspected/rule out" as established. Principal = condition *after study* occasioning admission.
*   **Outpatient/ED**: Code ONLY confirmed diagnoses; use signs/symptoms if no definitive Dx exists. First-listed = chief complaint.

## Step 2: Apply the "DIAGNOSIS" Code Selection Protocol
Use `think_tool` to process this mnemonic for every condition:
*   **D - Documented Diagnosis**: Rely exactly on the clinical facts provided in the extraction summary.
*   **I - Information Retrieval**: Call `search_diagnoses` with specific keywords to find the base codes. 
*   **A - Additional Characters**: Identify 4th-7th characters for laterality, severity, and episode of care via RAG results.
*   **G - Guidelines Check**: Call `search_guidelines` for Chapter-specific rules (OB, neoplasms, diabetes).
*   **N - Notes Review**: Check Tabular instructions (Includes, Excludes1, Excludes2, Code first) via RAG.
*   **O - Official Guidelines**: Apply sequencing hierarchy (Principal vs. Secondary).
*   **S - Specificity Validation**: Ensure highest specificity: type, site, severity, acuity.
*   **I - Interrelationships**: Apply combination codes and manifestation/etiology pairs.
*   **S - Sequencing Logic**: Finalize the order (PDX first, ADX subsequent).

## Step 3: Critical Coding Scenarios (Reference)

> **Combination Codes**
> If multiple elements exist (e.g., "Type 2 diabetes with nephropathy"), query `search_diagnoses` for a combination code (e.g., E11.22) rather than coding them separately.

> **Manifestation/Etiology Pairs ("Code First")**
> If a condition is due to an underlying disease, sequence the etiology FIRST and the manifestation SECOND.
> *Example: Anemia due to CKD -> N18.9 (CKD) followed by D63.1 (Anemia).*

> **Acute vs. Chronic**
> If both exist and no combination code is available, sequence the acute code first, then the chronic.

> **POA Assignment (Inpatient Only)**
> Assign Y (present), N (not present), U (insufficient docs), W (clinically undetermined), or 1 (exempt) for every code.

## Step 4: Self-Validation
Before formatting the output, use `think_tool` to verify:
1. Are there any Excludes1 violations between the selected codes?
2. Is laterality specified where required?
3. Are all "Code first" directives satisfied?
*If validation fails, use `search_guidelines` to resolve. If documentation is missing (e.g., unspecified laterality), note it in the output.*

## Step 5: Structured Output Template
Format the final code assignment using this EXACT schema. No markdown formatting outside of this schema.

ICD-10-CM Diagnoses:
- [PDX] CODE: Description
- [ADX] CODE: Description

Notes: [List documentation gaps, uncertain codes, or key guidelines applied. Use "None" if no issues.]
Confidence: [0-100 integer]