---
name: icd10-pcs-procedure
description: Use when assigning ICD-10-PCS procedure codes for inpatient hospital procedures after procedural facts are extracted.
---

# icd10-pcs-procedure

# ICD-10-PCS Procedure Coding Guidelines

## Role & Objective
Assign accurate, defensible ICD-10-PCS codes by mapping documented procedures to the official 7-character structure. Prioritize clinical accuracy, correct root operation selection, and proper sequencing over complex formatting.

## Critical PCS Rules
1. **Code to the Objective, Not the Name**: Assign the root operation that matches the *intent* of the procedure (e.g., "total mastectomy" → Resection; "partial colectomy" → Excision or Resection depending on extent).
2. **7-Axis Validation**: Every PCS code must be exactly 7 characters. Validate each axis against documentation:
   - Char 1: Section (0 = Medical & Surgical)
   - Char 2: Body System
   - Char 3: Root Operation
   - Char 4: Body Part
   - Char 5: Approach (0=Open, 3=Perc, 4=Per Endo, 7=Natural/Artif, 8=N/A Endo, X=External)
   - Char 6: Device (only if implanted/left behind)
   - Char 7: Qualifier
3. **Diagnostic vs. Therapeutic**: If a biopsy (Excision + Diagnostic qualifier) is followed by definitive treatment in the same session, code BOTH.
4. **Discontinued Procedures**: Code only what was actually performed. If aborted before the root operation, code as Inspection.
5. **Do Not Code Integral Steps**: Surgical approaches, closures, and routine drainage are not coded separately unless specifically required by guidelines.

## Sequencing & Assignment
- **PPX (Principal Procedure)**: The definitive procedure most closely related to the PDX, or the most resource-intensive if multiple unrelated procedures are performed.
- **APX (Additional Procedures)**: All other significant procedures performed during the encounter.
- Always sequence acute/therapeutic procedures before diagnostic/exploratory ones.

## Watch For (Common LLM Errors)
- Confusing Excision (partial removal) vs. Resection (complete removal)
- Mistaking Inspection for biopsy or therapy
- Assigning invalid approach characters (e.g., using "Open" for laparoscopic)
- Coding temporary instruments as permanent devices
- Selecting a diagnostic procedure as PPX when a therapeutic procedure was performed

## Tool Usage
- Query `search_procedures` and `search_guidelines` to verify root operations, body parts, and official PCS guidelines.
- Call `search_guidelines` for all official guideline, coding rule, or sequencing lookups.
- Use `think_tool` to resolve ambiguity before finalizing codes.

## Output Constraints (Strict)
- Do NOT output a separate PCS report, axis breakdowns, or rationale blocks.
- Do NOT add markdown formatting or extra commentary.
- Output ONLY the final code list following the agent's simplified output contract.
- If documentation lacks approach/body part details, assign the best-supported code and note the gap in `Notes`.