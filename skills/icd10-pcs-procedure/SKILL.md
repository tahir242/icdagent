---
name: icd10-pcs-procedure
description: Use when assigning ICD-10-PCS procedure codes for inpatient hospital procedures.
---

# icd10-pcs-procedure

## Role & Objective
Assign accurate ICD-10-PCS codes by mapping documented procedures to the official 7-character structure.

## Critical PCS Rules
1. **Objective over Name**: Code the *intent* of the procedure, not the eponym (e.g., "Whipple" $\rightarrow$ Pancreaticoduodenectomy).
2. **7-Axis Validation**: Every code must be exactly 7 characters:
   - Char 1: Section
   - Char 2: Body System
   - Char 3: Root Operation
   - Char 4: Body Part
   - Char 5: Approach
   - Char 6: Device (only if implanted/left behind)
   - Char 7: Qualifier
3. **Diagnostic vs. Therapeutic**: Code both if a biopsy is followed by definitive treatment in the same session.
4. **Discontinued Procedures**: Code only what was actually performed.
5. **Integral Steps**: Do not code routine closures or approaches separately.

## Sequencing
- **PPX (Principal)**: Definitive procedure most closely related to PDX.
- **APX (Additional)**: All other significant procedures.
- Sequence therapeutic before diagnostic.

## Common Pitfalls
- Excision (partial) vs. Resection (complete).
- Using "Open" for laparoscopic approach.
- Coding temporary instruments as permanent devices.

## Tool Usage
- `search_procedures` and `search_guidelines` to verify root operations and body parts.
- `think_tool` to resolve ambiguity.

## Output Constraints
- No axis breakdowns or rationale blocks.
- Output ONLY the final code list:
ICD-10-PCS Procedures:
- [PPX] CODE: Description
- [APX] CODE: Description