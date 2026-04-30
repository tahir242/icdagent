---
name: icd10-validation
description: Use when performing the final ICD-10-CM and ICD-10-PCS self-review.
---

# icd10-validation

## Role & Objective
Act as the final quality gate. Silently challenge every code. Ensure the final list is accurate, guideline-compliant, and defensible. **Do not output a validation report.**

## Critical Validation Checks (Internal)
### 1. Code Integrity
- ✅ CM codes exist in 2026 Tabular List.
- ✅ PCS codes are exactly 7 valid characters.

### 2. Sequencing
- ✅ **PDX**: Condition chiefly responsible for admission *after study*.
- ✅ **PPX**: Definitive procedure most closely related to PDX.
- ✅ Acute sequenced before chronic.

### 3. Specificity & Rules
- ✅ Laterality, acuity, and severity captured.
- ✅ Combination codes used where applicable.
- ✅ Excludes1/Excludes2 and "Code first" rules applied.

### 4. PCS 7-Axis Integrity
- ✅ Root operation matches the *objective*.
- ✅ Approach matches documentation.
- ✅ Device used ONLY if something remains post-procedure.

### 5. Consistency
- ✅ Diagnosis aligns with procedure (e.g., cholecystectomy $\rightarrow$ cholelithiasis).
- ✅ No significant documented conditions omitted.

## Handling Uncertainty
- If ambiguous, assign the **best-supported code** and note the gap in `Notes`.
- If a code cannot be confidently assigned, output `- None` and explain in `Notes`.

## Tool Usage (Silent)
- `search_diagnoses`, `search_procedures`, `search_guidelines` for evidence.
- `get_lessons_tool` for past corrections.
- `auto_log_failure_tool` ONLY if validation fails after internal correction.

## Output Constraints
- **NO** validation reports, checklists, or audit notes.
- **NO** markdown formatting or rationale blocks.
- Final answer must follow the simplified output contract in `AGENTS.md`.