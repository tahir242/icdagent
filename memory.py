"""
Memory module – stores and retrieves human corrections for the ICD-10 agent.

Improvements over previous version:
- Semantic similarity retrieval using sentence-transformers
- Timestamp tracking for lesson recency/decay
- Deduplication via content hashing
- Support for both positive (verified correct) and negative (corrected) examples
"""

import hashlib
import os
import time
from datetime import datetime
from difflib import SequenceMatcher

import chromadb
from sentence_transformers import SentenceTransformer
from project_paths import BASE_DIR, CHROMA_DIR, ensure_runtime_dirs

ensure_runtime_dirs()

# ============================================================
# ChromaDB client for corrections
# ============================================================
client = chromadb.PersistentClient(path=str(CHROMA_DIR / "corrections"))
collection = client.get_or_create_collection(
    "coding_corrections",
    metadata={"hnsw:space": "cosine"},  # cosine similarity for embeddings
)

# ============================================================
# TTL Cache for lesson retrieval (5 minutes)
# ============================================================
_lessons_cache = {}
_LESSONS_TTL = 300  # 5 minutes

# ============================================================
# Embedding model for semantic similarity (lightweight)
# ============================================================
_embedding_model = None
_LOCAL_EMBEDDING_MODEL_PATH = os.getenv(
    "MEMORY_EMBEDDING_MODEL_PATH",
    str(BASE_DIR / "models" / "embedding_models" / "all-MiniLM-L6-v2"),
)


def _get_embedding_model():
    """Lazy-load the sentence transformer model."""
    global _embedding_model
    if _embedding_model is None:
        try:
            _embedding_model = SentenceTransformer(
                _LOCAL_EMBEDDING_MODEL_PATH,
                local_files_only=True,
            )
        except Exception as e:
            print(f"⚠️ Offline embedding model load failed ({_LOCAL_EMBEDDING_MODEL_PATH}): {e}")
            # Fallback: return None to use hash-based retrieval
            _embedding_model = None
    return _embedding_model

def _embed_text(text: str) -> list[float] | None:
    """Embed text using sentence-transformers. Returns None if model unavailable."""
    model = _get_embedding_model()
    if model is None:
        return None
    embedding = model.encode(text, convert_to_numpy=True)
    return embedding.tolist()


def _content_hash(snippet: str, wrong_code: str) -> str:
    """Generate a deduplication hash for a correction."""
    content = f"{snippet.strip().lower()}|{wrong_code.strip().lower()}"
    return hashlib.md5(content.encode()).hexdigest()


# ============================================================
# SAVE a correction
# ============================================================
def save_correction(
    snippet: str,
    wrong_code: str,
    correct_code: str,
    explanation: str = "",
    verified_correct: bool = False,
) -> str:
    """
    Store a human QC correction.

    Args:
        snippet: The clinical text snippet that was miscoded
        wrong_code: The incorrect code that was assigned
        correct_code: The correct code
        explanation: Human explanation for the correction
        verified_correct: If True, this is a positive example (verified correct coding)

    Returns:
        Status message
    """
    doc = (
        f"Snippet: {snippet}\n"
        f"Wrong: {wrong_code} → Correct: {correct_code}\n"
        f"Lesson: {explanation}\n"
        f"Type: {'verified_correct' if verified_correct else 'correction'}"
    )

    correction_id = f"corr_{_content_hash(snippet, wrong_code)}"
    timestamp = datetime.now().isoformat()

    metadata = {
        "wrong": wrong_code,
        "correct": correct_code,
        "explanation": explanation,
        "timestamp": timestamp,
        "type": "correction" if not verified_correct else "verified",
    }

    # Check for existing entry (deduplication)
    existing = collection.get(ids=[correction_id])
    if existing and existing["ids"]:
        # Update existing entry with new timestamp
        collection.delete(ids=[correction_id])

    # Try to embed; fall back to raw text if embedding fails
    embedding = _embed_text(snippet)

    try:
        if embedding:
            collection.add(
                documents=[doc],
                metadatas=[metadata],
                ids=[correction_id],
                embeddings=[embedding],
            )
        else:
            # Without embeddings, Chroma will use IDF-based retrieval
            collection.add(
                documents=[doc],
                metadatas=[metadata],
                ids=[correction_id],
            )
        return f"✅ Correction saved: {wrong_code} → {correct_code}"
    except Exception as e:
        return f"⚠️ Correction save failed: {e}"


# ============================================================
# RETRIEVE lessons for similar cases
# ============================================================
def get_lessons(current_summary: str, top_k: int = 3) -> str:
    """
    Retrieve past human corrections for similar clinical scenarios.
    
    Uses TTL caching (5 minutes) to avoid redundant Chroma queries.
    Includes success rates and failure patterns for better learning.

    Uses semantic similarity (sentence-transformers) when available,
    falls back to TF-IDF via Chroma, then to SequenceMatcher as last resort.
    """
    # Check TTL cache first
    cache_key = f"{current_summary[:200]}_{top_k}"
    current_time = time.time()
    
    if cache_key in _lessons_cache:
        cached_result, cached_time = _lessons_cache[cache_key]
        if current_time - cached_time < _LESSONS_TTL:
            return cached_result  # Return cached result
    
    # Cache miss or expired – retrieve lessons
    result = _retrieve_lessons_internal(current_summary, top_k)
    
    # Store in cache with timestamp
    _lessons_cache[cache_key] = (result, current_time)
    
    return result


def _retrieve_lessons_internal(current_summary: str, top_k: int) -> str:
    """Internal lesson retrieval without caching."""
    data = collection.get(include=["documents", "metadatas"])
    documents = data.get("documents") or []
    metadatas = data.get("metadatas") or []

    if not documents or not metadatas:
        return "No previous corrections found."

    lessons = []
    
    # Try semantic similarity first
    embedding = _embed_text(current_summary)
    if embedding:
        try:
            results = collection.query(
                query_embeddings=[embedding],
                n_results=min(top_k * 2, len(documents)),  # Get more for filtering
                include=["documents", "metadatas", "distances"],
            )

            if results["documents"] and results["documents"][0]:
                for i, (doc, metadata) in enumerate(
                    zip(results["documents"][0], results["metadatas"][0])
                ):
                    # Apply time decay: recent corrections are more relevant
                    age_days = _compute_age_days(metadata.get("timestamp", ""))
                    decay_factor = max(0.5, 1.0 - (age_days / 365))  # Decay over 1 year
                    
                    # Include success rate if available
                    success_info = ""
                    success_rate = metadata.get("success_rate")
                    if success_rate is not None:
                        times_applied = metadata.get("times_applied", 0)
                        success_info = f", success: {success_rate:.0%} ({times_applied}x)"

                    lessons.append(
                        f"⚠️ LESSON (relevance: {decay_factor:.0%}{success_info}): "
                        f"Previously coded '{metadata.get('wrong', 'unknown')}' but corrected to "
                        f"'{metadata.get('correct', 'unknown')}'. "
                        f"Reason: {metadata.get('explanation', 'N/A')}"
                    )

                if lessons:
                    # Add failure patterns if available
                    failure_patterns = get_failure_patterns(top_k=2)
                    if failure_patterns:
                        lessons.append(f"\nCOMMON FAILURE PATTERNS:\n{failure_patterns}")
                    
                    return "\n".join(lessons[:top_k])
        except Exception:
            pass  # Fall through to fallback methods

    # Fallback: SequenceMatcher similarity
    result = _fallback_similarity(current_summary, documents, metadatas, top_k)
    
    # Add failure patterns
    failure_patterns = get_failure_patterns(top_k=2)
    if failure_patterns:
        result += f"\n\nCOMMON FAILURE PATTERNS:\n{failure_patterns}"
    
    return result

def _fallback_similarity(
    current_summary: str,
    documents: list[str],
    metadatas: list[dict],
    top_k: int,
) -> str:
    """Fallback similarity using SequenceMatcher when embeddings unavailable."""
    current_text = (current_summary or "").lower()
    scored_lessons = []

    for doc, metadata in zip(documents, metadatas):
        if not metadata:
            continue
        score = SequenceMatcher(None, current_text, (doc or "").lower()).ratio()

        # Apply time decay
        age_days = _compute_age_days(metadata.get("timestamp", ""))
        decay_factor = max(0.5, 1.0 - (age_days / 365))
        weighted_score = score * decay_factor

        scored_lessons.append((weighted_score, metadata))

    if not scored_lessons:
        return "No previous corrections found."

    top_lessons = sorted(scored_lessons, key=lambda x: x[0], reverse=True)[:top_k]
    lessons = [
        f"⚠️ LESSON (relevance: {score:.0%}): "
        f"Previously coded '{m.get('wrong', 'unknown')}' but corrected to "
        f"'{m.get('correct', 'unknown')}'. "
        f"Reason: {m.get('explanation', 'N/A')}"
        for score, m in top_lessons
    ]
    return "\n".join(lessons)


def _compute_age_days(timestamp_str: str) -> float:
    """Compute how many days ago a timestamp occurred."""
    if not timestamp_str:
        return 0  # No timestamp = treat as recent
    try:
        ts = datetime.fromisoformat(timestamp_str)
        delta = datetime.now() - ts
        return max(0, delta.total_seconds() / 86400)
    except (ValueError, TypeError):
        return 0


# ============================================================
# EXPORT all corrections
# ============================================================
def get_all_corrections() -> list[dict]:
    """Retrieve all stored corrections as a list of dicts."""
    data = collection.get(include=["documents", "metadatas"])
    corrections = []
    for doc, metadata in zip(data.get("documents", []), data.get("metadatas", [])):
        corrections.append(
            {
                "document": doc,
                "wrong": metadata.get("wrong", ""),
                "correct": metadata.get("correct", ""),
                "explanation": metadata.get("explanation", ""),
                "timestamp": metadata.get("timestamp", ""),
                "type": metadata.get("type", "correction"),
                "success_rate": metadata.get("success_rate", 0),
                "times_applied": metadata.get("times_applied", 0),
            }
        )
    return sorted(corrections, key=lambda x: x.get("timestamp", ""), reverse=True)


# ============================================================
# ENHANCED: Success tracking and auto-failure logging
# ============================================================

def record_lesson_application(correction_id: str, was_helpful: bool):
    """
    Record whether a lesson helped improve coding accuracy.
    Updates success rate metadata for the correction.
    
    Args:
        correction_id: The ID of the correction entry
        was_helpful: Whether applying this lesson improved the result
    """
    try:
        # Get current metadata
        existing = collection.get(ids=[correction_id], include=["metadatas"])
        if not existing or not existing.get("metadatas") or not existing["metadatas"][0]:
            return  # Correction not found
        
        metadata = existing["metadatas"][0]
        times_applied = metadata.get("times_applied", 0) + 1
        times_helpful = metadata.get("times_helpful", 0) + (1 if was_helpful else 0)
        success_rate = times_helpful / times_applied if times_applied > 0 else 0
        
        # Update metadata
        collection.update(
            ids=[correction_id],
            metadatas=[{
                **metadata,
                "times_applied": times_applied,
                "times_helpful": times_helpful,
                "success_rate": success_rate,
                "last_applied": datetime.now().isoformat(),
            }]
        )
    except Exception as e:
        # Non-critical: don't break the workflow if tracking fails
        print(f"⚠️ Failed to track lesson application: {e}")


def auto_log_failure(
    discharge_summary: str,
    attempted_codes: list[str],
    validation_report: str,
    confidence_score: int,
):
    """
    When agent fails validation, auto-log the failure pattern for future learning.
    Creates a "failure_pattern" lesson that helps future agents avoid the same mistake.
    
    Args:
        discharge_summary: The clinical text that was coded
        attempted_codes: List of codes the agent tried
        validation_report: The validation failure message
        confidence_score: The agent's confidence score
    """
    try:
        # Detect failure pattern type
        pattern_type = _detect_failure_type(validation_report)
        
        # Create failure pattern document
        failure_doc = (
            f"FAILURE PATTERN: {pattern_type}\n"
            f"Context: {discharge_summary[:300]}...\n"
            f"Attempted codes: {', '.join(attempted_codes)}\n"
            f"Validation failure: {validation_report[:200]}\n"
            f"Confidence: {confidence_score}%\n"
            f"Type: failure_pattern"
        )
        
        # Create unique ID for this pattern
        pattern_id = f"pattern_{hashlib.md5(f'{pattern_type}_{discharge_summary[:100]}'.encode()).hexdigest()}"
        
        # Check if similar pattern exists
        existing = collection.get(ids=[pattern_id])
        if existing and existing.get("ids"):
            # Update occurrence count
            collection.update(
                ids=[pattern_id],
                metadatas=[{
                    "type": "failure_pattern",
                    "pattern_type": pattern_type,
                    "occurrences": (existing["metadatas"][0].get("occurrences", 0) + 1),
                    "timestamp": datetime.now().isoformat(),
                }]
            )
        else:
            # Create new pattern entry
            collection.add(
                documents=[failure_doc],
                metadatas=[{
                    "type": "failure_pattern",
                    "pattern_type": pattern_type,
                    "occurrences": 1,
                    "timestamp": datetime.now().isoformat(),
                    "wrong": ", ".join(attempted_codes),
                    "correct": "See validation report",
                    "explanation": f"Auto-logged failure: {pattern_type}",
                }],
                ids=[pattern_id],
            )
        
        return f"✅ Auto-logged failure pattern: {pattern_type}"
    except Exception as e:
        return f"⚠️ Failed to auto-log failure: {e}"


def _detect_failure_type(validation_report: str) -> str:
    """Detect the type of coding failure from validation report."""
    report_lower = validation_report.lower()
    
    if any(term in report_lower for term in ["laterality", "left", "right", "bilateral"]):
        return "laterality_missed"
    elif any(term in report_lower for term in ["unspecified", "nos"]):
        return "unspecified_code"
    elif any(term in report_lower for term in ["sequencing", "principal", "pdx"]):
        return "sequencing_error"
    elif any(term in report_lower for term in ["specificity", "more specific"]):
        return "insufficient_specificity"
    elif any(term in report_lower for term in ["guideline", "excludes", "code first"]):
        return "guideline_violation"
    elif any(term in report_lower for term in ["invalid", "not found", "does not exist"]):
        return "invalid_code"
    else:
        return "general_validation_failure"


def get_failure_patterns(top_k: int = 5) -> str:
    """
    Retrieve common failure patterns to help agent avoid repeating mistakes.
    
    Args:
        top_k: Number of top patterns to return
    
    Returns:
        Formatted string of failure patterns
    """
    try:
        # Query for failure patterns
        results = collection.query(
            query_texts=["failure pattern"],
            n_results=min(top_k * 2, 20),
            include=["documents", "metadatas", "distances"],
        )
        
        if not results["documents"] or not results["documents"][0]:
            return ""
        
        # Filter for failure_pattern type only
        patterns = []
        for doc, metadata in zip(results["documents"][0], results["metadatas"][0]):
            if metadata.get("type") == "failure_pattern":
                occurrences = metadata.get("occurrences", 1)
                pattern_type = metadata.get("pattern_type", "unknown")
                patterns.append(
                    f"⚠️ PATTERN ({occurrences}x): {pattern_type.replace('_', ' ').title()}\n"
                    f"   Previous attempts: {metadata.get('wrong', 'N/A')}\n"
                    f"   Issue: {metadata.get('explanation', 'N/A')[:150]}"
                )
        
        if not patterns:
            return ""
        
        return "\n".join(patterns[:top_k])
    except Exception:
        return ""
