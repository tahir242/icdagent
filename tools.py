"""
Tools for the ICD-10 multi-agent coding system.

Tools are organized into groups for each sub-agent:
- all_tools: Complete list (for main agent / coordinator)
- extraction_tools: Clinical extraction and reasoning support
- diagnosis_tools: ICD-10-CM coding support
- procedure_tools: ICD-10-PCS coding support
- validation_tools: Code verification support
"""

from functools import lru_cache
import json
import os
import re
import threading
import spacy
import json
import re
import warnings as py_warnings
from functools import lru_cache
from typing import List, Dict, Any, Tuple, Optional
from spacy.matcher import PhraseMatcher
from spacy.util import filter_spans
from spacy.tokens import Span
from langchain.tools import tool
from dotenv import load_dotenv
from memory import get_lessons, save_correction, auto_log_failure, get_failure_patterns
from thinking_runtime import record_thought
from retrieval import get_hybrid_retriever

load_dotenv()

RAG_DEFAULT_RESULTS = int(os.getenv("RAG_DEFAULT_RESULTS", "10"))
RAG_DOC_MAX_CHARS = int(os.getenv("RAG_DOC_MAX_CHARS", "1500"))
RAG_TOTAL_MAX_CHARS = int(os.getenv("RAG_TOTAL_MAX_CHARS", "1500"))
LESSONS_TOP_K = int(os.getenv("LESSONS_TOP_K", "2"))
LESSONS_MAX_CHARS = int(os.getenv("LESSONS_MAX_CHARS", "1600"))
MEDSPACY_DEFAULT_MAX_ENTITIES = int(os.getenv("MEDSPACY_DEFAULT_MAX_ENTITIES", "150"))
MEDSPACY_SENTENCE_MAX_CHARS = int(os.getenv("MEDSPACY_SENTENCE_MAX_CHARS", "300"))
MEDSPACY_SUMMARY_MAX_CHARS = int(os.getenv("MEDSPACY_SUMMARY_MAX_CHARS", "1200"))

# ============================================================
# TOOL 0: Shared reasoning support – used by think_tool and captured by the agent runner
# ============================================================
# Thread-safe reasoning capture
_reasoning_steps: list[str] = []
_steps_lock = threading.Lock()


def _clean_thought_text(value: str) -> str:
    """Normalize noisy model artifacts in thought text."""
    text = (value or "").replace("<|", "").replace("|>", "")
    text = re.sub(r'(?<!\s)\|(?!\s)', "", text)
    text = re.sub(r'[\|"]{2,}', " ", text)
    text = text.replace("<", "").replace(">", "")
    text = re.sub(r'\s+', " ", text).strip()
    text = text.replace('""', '"').strip(" \"")
    return text
    
@tool()
def think_tool(
    step: str,
    reasoning: str,
    confidence: int = 80,
    key_insights: list[str] | None = None,
    uncertainties: list[str] | None = None,
    next_action: str = "continue"
) -> str:
    """
    Structured internal reasoning tracker for clinical coding.
    Use this to document decisions, flag documentation gaps, and plan tool usage.
    Do NOT include this tool's output in the final answer.
    """
    if key_insights is None: key_insights = []
    if uncertainties is None: uncertainties = []

    # Clamp confidence to valid range (kept for compatibility, hidden from output)
    confidence = max(0, min(100, int(confidence)))
    clean_step = _clean_thought_text(step)
    clean_reasoning = _clean_thought_text(reasoning)
    clean_insights = [_clean_thought_text(item) for item in key_insights if _clean_thought_text(item)]
    clean_gaps = [_clean_thought_text(item) for item in uncertainties if _clean_thought_text(item)]

    # Build compact, structured log
    thought = (
        f"[{clean_step}] {clean_reasoning} (Conf: {confidence}%)| "
        f"Insights: {', '.join(clean_insights) or 'None'} | "
        f"Gaps: {', '.join(clean_gaps) or 'None'} | "
        f"Next: {next_action}"
    )

    print(f"[THINK] {thought} \n\n")
    record_thought(thought)

    # Thread-safe capture for post-run analysis
    with _steps_lock:
        _reasoning_steps.append(thought)

    # Explicit directive for Gemma4
    return (
        f"✅ Reasoning step '{step}' captured. "
        f"Proceed with: {next_action}. "
        f"If documentation gaps exist, query RAG/MCP before finalizing codes. "
        f"Keep all reasoning internal; output ONLY the final code contract."
    )


def get_reasoning_steps() -> list[str]:
    """Return and clear accumulated reasoning steps (thread-safe)."""
    with _steps_lock:
        steps = _reasoning_steps.copy()
        _reasoning_steps.clear()
    return steps


def _truncate_text(text: str, max_chars: int) -> str:
    """Trim long text while preserving the beginning where labels usually appear."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "... [truncated]"


def _format_clinical_summary(grouped: Dict[str, List[str]], acuity: List[str], laterality: List[str]) -> Dict[str, Any]:
    summary_lines: List[str] = []
    if grouped.get("findings"):
        summary_lines.append(f"Findings: {', '.join(grouped['findings'])}")
    if grouped.get("procedures"):
        summary_lines.append(f"Procedures: {', '.join(grouped['procedures'])}")
    if grouped.get("medications"):
        summary_lines.append(f"Medications: {', '.join(grouped['medications'])}")
    if grouped.get("anatomy"):
        summary_lines.append(f"Anatomy: {', '.join(grouped['anatomy'])}")
    if acuity:
        summary_lines.append(f"Acuity: {', '.join(sorted(set(acuity)))}")
    if laterality:
        summary_lines.append(f"Laterality: {', '.join(sorted(set(laterality)))}")
    if grouped.get("negated_or_historical"):
        summary_lines.append(
            f"Negated/Historical: {', '.join(grouped['negated_or_historical'])}"
        )

    summary_text = _truncate_text(" | ".join(summary_lines), MEDSPACY_SUMMARY_MAX_CHARS)
    return {
        "text": summary_text,
        "sections": grouped,
        "signals": {
            "acuity": sorted(set(acuity)),
            "laterality": sorted(set(laterality)),
        },
    }


# ============================================================
# TOOL 1: Clinical NLP extraction with MedSpaCy/SciSpaCy
# ============================================================

# Load domain-specific phrase matchers from external JSON
VOCAB_PATH = os.path.join(os.path.dirname(__file__), "data", "vocabularies.json")
try:
    with open(VOCAB_PATH, "r", encoding="utf-8") as f:
        vocab = json.load(f)
        CLINICAL_FINDINGS = vocab.get("CLINICAL_FINDINGS", [])
        CLINICAL_PROCEDURES = vocab.get("CLINICAL_PROCEDURES", [])
        CLINICAL_ANATOMY = vocab.get("CLINICAL_ANATOMY", [])
        CLINICAL_MEDS = vocab.get("CLINICAL_MEDS", [])
except Exception as e:
    print(f"Warning: Could not load vocabularies.json: {e}")
    CLINICAL_FINDINGS = []
    CLINICAL_PROCEDURES = []
    CLINICAL_ANATOMY = []
    CLINICAL_MEDS = []

# Legacy array start (to match if anything else was expecting it)

@lru_cache(maxsize=1)
def _get_clinical_nlp_bundle() -> Tuple[Any, str, Tuple[str, ...]]:
    warnings_list: List[str] = []
    pipeline_name = "unknown"
    nlp: Optional[Any] = None

    # 1️⃣ Prefer SciSpacy for statistical clinical NER
    for model in ("en_core_sci_md", "en_ner_bc5cdr_md"):
        try:
            nlp = spacy.load(model)
            pipeline_name = model
            break
        except Exception as e:
            warnings_list.append(f"SciSpacy {model} unavailable: {e}")

    # 2️⃣ Fallback to MedSpaCy (includes ConText & Sectionizer automatically)
    if nlp is None:
        try:
            import medspacy
            nlp = medspacy.load()
            pipeline_name = "medspacy.load"
        except Exception as e:
            warnings_list.append(f"MedSpaCy unavailable: {e}")

    # 3️⃣ Fallback to blank spaCy
    if nlp is None:
        nlp = spacy.blank("en")
        pipeline_name = "spacy.blank(en)"
        warnings_list.append("Falling back to blank model; using rule-based extraction only.")

    # Ensure sentencizer
    if "sentencizer" not in nlp.pipe_names:
        nlp.add_pipe("sentencizer", first=True)

    # ✅ Fix: Only try ConText if using medspacy.load(), otherwise skip gracefully
    if pipeline_name == "medspacy.load" and "con_txt" not in nlp.pipe_names:
        try:
            from medspacy.context import ConText
            nlp.add_pipe("con_txt")
        except Exception as e:
            warnings_list.append(f"ConText failed to load: {e}. Using heuristic fallback.")

    return nlp, pipeline_name, tuple(warnings_list)


def _parse_sections(text: str) -> List[Dict[str, Any]]:
    sections: List[Dict] = []
    for match in re.finditer(r"(?m)^(?P<header>[A-Za-z][A-Za-z /()'&-]{2,60}):\s*$", text):
        if sections:
            sections[-1]["end_char"] = match.start()
        sections.append({
            "name": match.group("header").strip(),
            "start_char": match.end(),
            "end_char": len(text),
        })
    if not sections:
        return [{"name": "document", "start_char": 0, "end_char": len(text)}]
    if sections[0]["start_char"] > 0:
        sections.insert(0, {"name": "document", "start_char": 0, "end_char": sections[0]["start_char"]})
    sections[-1]["end_char"] = len(text)
    return sections


def _get_context(ent: Span) -> Dict[str, Any]:
    ctx = {"is_negated": False, "is_historical": False, "is_uncertain": False, "is_family": False, "is_hypothetical": False, "laterality": None, "acuity": None}
    try:
        if hasattr(ent._, "is_negated"): ctx["is_negated"] = bool(ent._.is_negated)
        if hasattr(ent._, "is_historical"): ctx["is_historical"] = bool(ent._.is_historical)
        if hasattr(ent._, "is_uncertain"): ctx["is_uncertain"] = bool(ent._.is_uncertain)
        if hasattr(ent._, "is_family"): ctx["is_family"] = bool(ent._.is_family)
        if hasattr(ent._, "is_hypothetical"): ctx["is_hypothetical"] = bool(ent._.is_hypothetical)
    except Exception:
        pass

    sent = ent.sent.text.lower() if hasattr(ent, "sent") else ""

    if not any(v for k, v in ctx.items() if isinstance(v, bool)):
        # Tighter heuristic matching to avoid false negatives on historical mentions
        ctx["is_negated"] = any(t in sent for t in [" no ", " not ", " negative for ", " without ", " denies ", " benign ", " normal "])
        ctx["is_historical"] = any(t in sent for t in [" history of ", " known case of ", " since ", " previously ", " status post ", "post-", "h/o "])
        ctx["is_uncertain"] = any(t in sent for t in [" possible ", " probable ", " suspected ", " query ", " rule out ", " r/o "])
        ctx["is_family"] = " family history " in sent or " family hx " in sent
        ctx["is_hypothetical"] = any(t in sent for t in [" if ", " consider ", " evaluate for ", " should ", " recommended "])

    if "acute-on-chronic" in sent or "acute on chronic" in sent:
        ctx["acuity"] = "acute-on-chronic"
    elif "acute" in sent:
        ctx["acuity"] = "acute"
    elif "chronic" in sent:
        ctx["acuity"] = "chronic"

    if "bilateral" in sent or "both" in sent:
        ctx["laterality"] = "bilateral"
    elif "left" in sent:
        ctx["laterality"] = "left"
    elif "right" in sent:
        ctx["laterality"] = "right"

    return ctx


# ✅ Fix: Return keys that EXACTLY match the `grouped` dict keys
def _infer_bucket(text: str, label: str) -> str:
    lower = text.lower()
    if any(h in lower for h in CLINICAL_PROCEDURES): return "procedures"
    if any(h in lower for h in CLINICAL_MEDS): return "medications"
    if any(h in lower for h in CLINICAL_ANATOMY): return "anatomy"
    
    label_l = label.lower()
    if any(t in label_l for t in ("drug", "chem", "pharmac")): return "medications"
    if any(t in label_l for t in ("anat", "body")): return "anatomy"
    if any(t in label_l for t in ("proc", "treatment", "test")): return "procedures"
    return "findings"


def _extract_rule_matches(nlp: Any, doc: Any) -> List[Span]:
    matcher = PhraseMatcher(nlp.vocab, attr="LOWER")
    all_terms = CLINICAL_FINDINGS + CLINICAL_PROCEDURES + CLINICAL_ANATOMY + CLINICAL_MEDS
    patterns = [nlp.make_doc(term) for term in all_terms]
    matcher.add("CLINICAL", patterns)
    
    rule_spans = []
    for match_id, start, end in matcher(doc):
        rule_spans.append(doc[start:end])
    return rule_spans


@tool(parse_docstring=True)
def medspacy_extract_clinical_context(clinical_text: str, max_entities: int = MEDSPACY_DEFAULT_MAX_ENTITIES) -> str:
    """Extract clinical entities, abbreviations, and contextual flags from medical text.

    Uses MedSpaCy when available, with SciSpaCy abbreviation detection and
    heuristic fallbacks for section parsing and context cues such as negation,
    history, and uncertainty.

    Args:
        clinical_text: Raw clinical note, discharge summary, or operative report.
        max_entities: Maximum entities to return in the JSON payload.

    Returns:
        JSON string containing sections, entities, and a consolidated clinical summary.
    """
    print(clinical_text)
    text = clinical_text.strip()
    if not text:
        return json.dumps({"status": "error", "message": "clinical_text is empty"}, indent=2)

    nlp, pipeline_name, warnings_list = _get_clinical_nlp_bundle()
    sections = _parse_sections(text)
    doc = nlp(text)

    # Combine statistical NER + rule-based matches, deduplicate overlaps
    all_spans = list(getattr(doc, "ents", [])) + _extract_rule_matches(nlp, doc)
    unique_spans = filter_spans(all_spans)
    unique_spans = sorted(unique_spans, key=lambda x: x.start_char)[:max_entities]

    entities: List[Dict] = []
    seen_texts = set()  # ✅ Fix: Prevent duplicate text entries in summary
    acuity_hits: List[str] = []
    laterality_hits: List[str] = []
    
    grouped: Dict[str, List[str]] = {
        "findings": [],
        "procedures": [],
        "medications": [],
        "anatomy": [],
        "negated_or_historical": [],
    }

    for ent in unique_spans:
        ent_text = ent.text.strip()
        if not ent_text: continue

        context = _get_context(ent)
        sentence = ent.sent.text.strip() if hasattr(ent, "sent") else ""
        if len(sentence) > MEDSPACY_SENTENCE_MAX_CHARS:
            sentence = sentence[:MEDSPACY_SENTENCE_MAX_CHARS] + "..."

        bucket = _infer_bucket(ent_text, ent.label_)
        section = next((s["name"] for s in sections if s["start_char"] <= ent.start_char < s["end_char"]), "document")

        if context.get("acuity"):
            acuity_hits.append(context["acuity"])
        if context.get("laterality"):
            laterality_hits.append(context["laterality"])

        entities.append({
            "text": ent_text,
            "label": ent.label_,
            "bucket": bucket,
            "start_char": ent.start_char,
            "end_char": ent.end_char,
            "section": section,
            "sentence": sentence,
            "context": context,
        })

        if context.get("is_negated") or context.get("is_historical"):
            key = ent_text.lower()
            if key not in seen_texts:
                seen_texts.add(key)
                grouped["negated_or_historical"].append(ent_text)

        target_list = grouped.get(bucket, grouped["findings"])
        key = ent_text.lower()
        if key not in seen_texts:
            seen_texts.add(key)
            target_list.append(ent_text)

    if not unique_spans:
        warnings_list = list(warnings_list) + ["No NLP entities detected; rely on section parsing and direct note review."]

    clinical_summary = _format_clinical_summary(grouped, acuity_hits, laterality_hits)

    result = {
        "status": "ok",
        "pipeline": pipeline_name,
        "warnings": list(warnings_list),
        "sections": sections,
        "clinical_summary": clinical_summary,
        "entities": entities,
        "summary": grouped,
    }
    
    print(json.dumps(result, indent=2))
    return json.dumps(result, indent=2)

# ============================================================
# TOOL 2: RAG context retrieval from local ICD-10 code store
# ============================================================
def _parse_evidence_block(collection: str, text: str, source: str) -> Dict[str, str]:
    cleaned = (text or "").strip()
    code = ""
    description = ""
    guideline_note = ""

    if "|" in cleaned and collection in {"diagnoses", "procedures"}:
        parts = [p.strip() for p in cleaned.split("|")]
        code = parts[0] if parts else ""
        description = parts[1] if len(parts) > 1 else ""
        guideline_note = " | ".join(parts[2:]).strip() if len(parts) > 2 else ""
    elif collection == "guidelines":
        guideline_note = cleaned
    else:
        description = cleaned

    return {
        "code": code,
        "description": description,
        "guideline_note": guideline_note,
        "source": source,
    }


def _format_evidence_block(block: Dict[str, str]) -> str:
    return f"{block.get('code', '')} | {block.get('description', '')} | {block.get('guideline_note', '')}".strip()


def _search_collection(collection: str, query: str, max_results: int, max_chars: int) -> str:
    retriever = get_hybrid_retriever(collection)
    if not retriever:
        return json.dumps({
            "status": "error",
            "message": f"{collection.capitalize()} RAG store not available. Build it by running: python rag_builder.py",
            "collection": collection,
        }, indent=2)
    
    docs = retriever.invoke(query, k=max(1, min(max_results, 10)))
    if not docs:
        return json.dumps({
            "status": "ok",
            "message": f"No matching results found in the {collection} RAG store.",
            "collection": collection,
            "query": query,
            "evidence_blocks": [],
        }, indent=2)

    evidence_blocks: List[Dict[str, str]] = []
    formatted_blocks: List[str] = []
    total_chars = 0

    for doc in docs:
        source = (doc.metadata or {}).get("source", "")
        chunk = _truncate_text(doc.page_content, RAG_DOC_MAX_CHARS)
        block = _parse_evidence_block(collection, chunk, source)
        block_text = _format_evidence_block(block)

        next_total = total_chars + len(block_text) + 5
        if evidence_blocks and next_total > max_chars:
            break

        evidence_blocks.append(block)
        formatted_blocks.append(block_text)
        total_chars = next_total

    result = {
        "status": "ok",
        "collection": collection,
        "query": query,
        "evidence_blocks": evidence_blocks,
        "formatted_blocks": formatted_blocks,
        "total_blocks": len(evidence_blocks),
    }

    print(f"Query: '{query}', max_results: {max_results}, max_chars: {max_chars} \n")
    print(f"Retrieved {len(evidence_blocks)} evidence blocks from {collection} RAG store (Total chars: {total_chars}/{max_chars}) \n")
    print("\\n---\\n".join(formatted_blocks) + "\n\n")
    return json.dumps(result, indent=2)

@tool(parse_docstring=True)
def search_diagnoses(query: str, max_results: int = RAG_DEFAULT_RESULTS, max_chars: int = RAG_TOTAL_MAX_CHARS) -> str:
    """Search the ICD-10-CM Diagnoses database for exact codes or semantic clinical matches.
    
    Args:
        query: Clinical diagnosis description or specific ICD-10-CM code.
        max_results: Maximum retrieved passages.
        max_chars: Maximum total response size.

    Returns:
        JSON string with structured evidence blocks (Code | Description | Guideline Note).
    """
    return _search_collection("diagnoses", query, max_results, max_chars)

@tool(parse_docstring=True)
def search_procedures(query: str, max_results: int = RAG_DEFAULT_RESULTS, max_chars: int = RAG_TOTAL_MAX_CHARS) -> str:
    """Search the ICD-10-PCS Procedures database for exact codes or semantic procedural matches.
    
    Args:
        query: Clinical procedure description or specific ICD-10-PCS code.
        max_results: Maximum retrieved passages.
        max_chars: Maximum total response size.

    Returns:
        JSON string with structured evidence blocks (Code | Description | Guideline Note).
    """
    return _search_collection("procedures", query, max_results, max_chars)

@tool(parse_docstring=True)
def search_guidelines(query: str, max_results: int = RAG_DEFAULT_RESULTS, max_chars: int = RAG_TOTAL_MAX_CHARS) -> str:
    """Search the official ICD-10 Coding Guidelines and rules for sequencing and primary/secondary coding instructions.
    
    Args:
        query: Question about coding rules, guidelines, or sequencing.
        max_results: Maximum retrieved passages.
        max_chars: Maximum total response size.

    Returns:
        JSON string with structured evidence blocks (Code | Description | Guideline Note).
    """
    return _search_collection("guidelines", query, max_results, max_chars)

# ============================================================
# TOOL 3: Retrieve past human corrections for similar cases
# ============================================================
@tool(parse_docstring=True)
def get_lessons_tool(current_summary: str, max_chars: int = LESSONS_MAX_CHARS) -> str:
    """Retrieve past human corrections for similar clinical scenarios.

    Args:
        current_summary: Current discharge summary text to find similar cases.
        max_chars: Maximum response size in characters.

    Returns:
        JSON string formatted as Pattern -> Correction -> Rationale.
    """
    print(f"📚 [get_lessons_tool] Retrieving lessons for current summary: '{current_summary[:100]}...'")
    raw_lessons = get_lessons(current_summary, top_k=LESSONS_TOP_K)

    if not raw_lessons or "No previous corrections found." in raw_lessons:
        return json.dumps({
            "status": "ok",
            "message": "No previous corrections found.",
            "lessons": [],
            "failure_patterns": "",
        }, indent=2)

    parts = raw_lessons.split("COMMON FAILURE PATTERNS:")
    lesson_text = parts[0].strip()
    failure_patterns = parts[1].strip() if len(parts) > 1 else ""

    lessons: List[Dict[str, str]] = []
    formatted: List[str] = []
    for line in lesson_text.splitlines():
        line = line.strip()
        if not line:
            continue

        relevance_match = re.search(r"LESSON \(relevance: ([^\)]*)\)", line)
        relevance = relevance_match.group(1) if relevance_match else ""

        match = re.search(
            r"Previously coded '([^']+)' but corrected to '([^']+)'. Reason: (.+)$",
            line,
        )

        if match:
            wrong_code, correct_code, rationale = match.groups()
            pattern = f"Wrong code assigned: {wrong_code}"
            correction = f"{wrong_code} -> {correct_code}"
            rationale = rationale.strip()
        else:
            pattern = "Similar-case correction"
            correction = "See lesson detail"
            rationale = line

        lesson = {
            "pattern": pattern,
            "correction": correction,
            "rationale": rationale,
            "relevance": relevance,
        }
        lessons.append(lesson)
        formatted.append(f"{pattern} -> {correction} -> {rationale}")

    result = {
        "status": "ok",
        "lessons": lessons,
        "formatted_lessons": formatted,
        "failure_patterns": failure_patterns,
    }

    return _truncate_text(json.dumps(result, indent=2), max_chars)


# ============================================================
# TOOL 4: Save a human QC correction to the learning store
# ============================================================
@tool(parse_docstring=True)
def save_human_correction(snippet: str, wrong_code: str, correct_code: str, explanation: str = "") -> str:
    """Store a human QC correction for agent learning.

    Args:
        snippet: Clinical text snippet where correction applies.
        wrong_code: Incorrectly assigned code.
        correct_code: Corrected code.
        explanation: Reason for correction.

    Returns:
        Confirmation message with the correction saved.
    """
    save_correction(snippet, wrong_code, correct_code, explanation)
    return f"✅ Correction saved: {wrong_code} → {correct_code}"


# ============================================================
# TOOL 5: Auto-log validation failures for learning
# ============================================================
@tool(parse_docstring=True)
def auto_log_failure_tool(discharge_summary: str, codes_str: str, validation_report: str, confidence: int) -> str:
    """Auto-log validation failures for agent learning.

    Args:
        discharge_summary: The clinical text that was coded.
        codes_str: Comma-separated list of attempted codes.
        validation_report: The validation failure message.
        confidence: The agent's confidence score (0-100).

    Returns:
        Confirmation that failure pattern was logged.
    """
    codes = [c.strip() for c in codes_str.split(",") if c.strip()]
    return auto_log_failure(discharge_summary, codes, validation_report, confidence)


# ============================================================
# TOOL GROUPS – assigned per sub-agent in sub_agents.py
# ============================================================

# Main agent (coordinator) gets ALL tools
all_tools = [
    think_tool,
    medspacy_extract_clinical_context,
    search_diagnoses,
    search_procedures,
    search_guidelines,
    get_lessons_tool,
    save_human_correction,
    auto_log_failure_tool,
]

# Extraction agent – clinical NLP + reasoning
extraction_tools = [
    think_tool,
    medspacy_extract_clinical_context,
]

# Diagnosis agent – ICD-10-CM coding with MCP lookup + RAG + lessons
diagnosis_tools = [
    think_tool,
    search_diagnoses,
    search_guidelines,
    get_lessons_tool,
]

# Procedure agent – ICD-10-PCS coding with RAG + lessons
procedure_tools = [
    think_tool,
    search_procedures,
    search_guidelines,
    get_lessons_tool,
]

# Validation agent – all verification tools
validation_tools = [
    think_tool,
    search_diagnoses,
    search_procedures,
    search_guidelines,
    get_lessons_tool,
]


# ============================================================
# PLAIN FUNCTIONS (for FastAPI endpoints – not @tool decorated)
# ============================================================

def save_correction_api(snippet: str, wrong_code: str, correct_code: str, explanation: str = "") -> str:
    """Plain function that FastAPI can call directly (no @tool decoration)."""
    save_correction(snippet, wrong_code, correct_code, explanation)
    return f"✅ Correction saved: {wrong_code} → {correct_code}"
