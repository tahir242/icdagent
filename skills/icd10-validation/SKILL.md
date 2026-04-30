---
name: icd10-validation
description: Use when performing the final ICD-10-CM and ICD-10-PCS self-review before returning the single-agent result.
---
# icd10-validation
# ICD-10 Final Validation Guidelines

## Role & Objective
Act as a final quality gate. Silently challenge every code before output. Your goal is to catch errors internally and ensure the final code list is accurate, guideline-compliant, and defensible. **Do not output a separate validation report.**

## Critical Validation Checks (Silent Internal Pass)
Before finalizing output, verify each point below. If any check fails, correct the code internally or flag the issue in `Notes`.

### Code Existence & Status
- ✅ Every ICD-10-CM code must exist in the 2026 Tabular List.
- ✅ Every ICD-10-PCS code must be exactly 7 valid characters.
- ✅ Use `search_guidelines` to verify ambiguous codes.

### Sequencing Accuracy
- ✅ **PDX**: Is this truly the condition chiefly responsible for admission *after study*?
- ✅ **PPX**: Is this the definitive procedure most closely related to the PDX?
- ✅ Acute conditions sequenced before chronic when both are documented.

### Specificity & Completeness
- ✅ Laterality captured when documented (left/right/bilateral).
- ✅ Acuity/severity/stage included when supported by documentation.
- ✅ Combination codes used where applicable (e.g., hypertensive CKD).
- ✅ Excludes1/Excludes2 rules applied correctly.
- ✅ "Code first" / "Use additional code" instructions followed.

### PCS 7-Axis Integrity
- ✅ Root operation matches the *objective* of the procedure.
- ✅ Approach character matches documentation (0=Open, 3=Perc, 4=Perc Endo, etc.).
- ✅ Device character used ONLY if something remains post-procedure.
- ✅ Qualifier character applied when required.

### Consistency & Omissions
- ✅ Diagnosis codes align with procedure codes (e.g., cholecystectomy → cholelithiasis).
- ✅ No significant documented conditions or procedures were omitted.
- ✅ Historical conditions coded with Z-codes only, not as active diagnoses.

## Handling Uncertainty
- If documentation is ambiguous (e.g., missing laterality, unclear linkage), assign the **best-supported code** and note the gap in `Notes`.
- If a code cannot be confidently assigned, output `- None` for that section and explain why in `Notes`.

## Tool Usage (Silent)
- `search_diagnoses`, `search_procedures`, `search_guidelines`: Primary sources for guideline evidence and code definitions.
- Call `search_guidelines` for all official guideline, coding rule, or sequencing lookups.
- `get_lessons_tool`: Check for past corrections on similar cases.
- `auto_log_failure_tool`: Use ONLY if validation still fails after internal correction attempts.

## Output Constraints (Strict)
- **Do NOT** output a validation report, checklist, or audit notes.
- **Do NOT** add markdown formatting, rationale blocks, or intermediate reasoning.
- **Do NOT** claim validation passed if major ambiguity remains—flag it in `Notes` instead.
- The final answer must follow the simplified output contract defined in `AGENTS.md`.

## Optimization Tips
- Be direct and imperative in internal reasoning.
- Avoid filler phrases like "After validation..." or "The codes have been checked..."
- If a check fails, correct silently or note concisely: "Laterality unspecified in documentation."
- Keep `Notes` brief and actionable: "Query provider for laterality of knee procedure."