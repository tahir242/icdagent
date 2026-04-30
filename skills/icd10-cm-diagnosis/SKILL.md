---
name: icd10-cm-diagnosis
description: INVOKE THIS SKILL when assigning ICD-10-CM diagnosis codes based on the clinical extraction summary.
---

# icd10-cm-diagnosis

## Overview
Assign accurate ICD-10-CM diagnosis codes by synthesizing extraction summaries with official guidelines.
**Golden Rule**: Code only what is documented. Never assume.

## Workflow
1. **Encounter Rules**: 
   - **Inpatient**: Code "probable/suspected/rule out" as established. PDX = condition *after study* occasioning admission.
   - **Outpatient**: Code ONLY confirmed diagnoses.
2. **The "DIAGNOSIS" Protocol**:
   - **D**ocumented Diagnosis: Use extraction summary facts.
   - **I**nformation Retrieval: `search_diagnoses` for base codes.
   - **A**dditional Characters: Find 4th-7th characters (laterality, severity).
   - **G**uidelines Check: `search_guidelines` for chapter-specific rules.
   - **N**otes Review: Check Tabular (Includes, Excludes1/2, Code first).
   - **O**fficial Guidelines: Apply sequencing (PDX vs ADX).
   - **S**pecificity Validation: Ensure highest specificity (type, site, severity).
   - **I**nterrelationships: Apply combination codes and manifestation/etiology pairs.
   - **S**equencing Logic: Finalize order (PDX first).

## Critical Scenarios
- **Combination Codes**: Use one combination code (e.g., E11.22) instead of two separate codes if available.
- **Etiology/Manifestation**: Sequence Etiology FIRST, Manifestation SECOND.
- **Acute vs. Chronic**: Sequence Acute first, then Chronic.
- **POA (Inpatient)**: Assign Y, N, U, W, or 1 for every code.

## Validation & Output
- **Self-Check**: Verify Excludes1 violations and "Code first" directives.
- **Output Format**:
ICD-10-CM Diagnoses:
- [PDX] CODE: Description
- [ADX] CODE: Description

Notes: [Gaps or guidelines applied]
Confidence: [0-100]