"""
ICD-10 Coding Agent Runner.
Focus: Reliable execution, clean output, Ollama/Gemma4 optimized.
"""
import os
import atexit
from contextlib import ExitStack
from uuid import uuid4
from dotenv import load_dotenv

from langchain.chat_models import init_chat_model
from langchain_core.runnables import RunnableConfig
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.sqlite import SqliteStore
from project_paths import DB_DIR, ensure_runtime_dirs
from thinking_runtime import bind_run_context, unbind_run_context, get_all_thought_text, finalize_run
from system_prompt import agent_prompt

load_dotenv()
ensure_runtime_dirs()

# ============================================================
# 1. LLM CONFIGURATION (Fixed: Removed hardcoded Gemini override)
# ============================================================
LLM_PROVIDER_STRING = os.getenv("LLM_PROVIDER_STRING", "ollama:gemma4:31b")
_provider = LLM_PROVIDER_STRING.split(":")[0].lower()
_is_ollama = _provider == "ollama"

LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "180" if not _is_ollama else "120"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))

# Initialize LLM with provider-aware settings
llm_kwargs = {"temperature": 0.1, "max_retries": LLM_MAX_RETRIES, "timeout": LLM_TIMEOUT}
if _is_ollama:
    # Ollama automatically uses localhost:11434 unless OLLAMA_HOST is set
    llm_kwargs["model_kwargs"] = {"base_url": os.getenv("OLLAMA_HOST", "http://localhost:11434")}

llm = init_chat_model(model=LLM_PROVIDER_STRING, **llm_kwargs)

# ============================================================
# 2. PERSISTENCE & STORAGE
# ============================================================
CHECKPOINT_DB = os.getenv("AGENT_CHECKPOINT_DB_PATH", str(DB_DIR / "agent_checkpoints.sqlite3"))
STORE_DB = os.getenv("AGENT_STORE_DB_PATH", str(DB_DIR / "agent_store.sqlite3"))

_resources = ExitStack()
checkpointer = _resources.enter_context(SqliteSaver.from_conn_string(CHECKPOINT_DB))
checkpointer.setup()
store = _resources.enter_context(SqliteStore.from_conn_string(STORE_DB))
store.setup()
atexit.register(_resources.close)

# ============================================================
# 3. AGENT INITIALIZATION
# ============================================================
from tools import all_tools

single_agent = create_deep_agent(
    name="icd10-coding-agent",
    model=llm,
    memory=["/memories/AGENTS.md"],
    skills=["/skills/"],
    tools=all_tools,
    checkpointer=checkpointer,
    backend=FilesystemBackend(root_dir=".", virtual_mode=True),
    store=store,
    system_prompt=agent_prompt
)

# ============================================================
# 4. CORE RUNNER FUNCTION
# ============================================================
def run_coding_agent(
    discharge_summary: str,
    thread_id: str | None = None,
    max_retries: int = 2,
    run_id: str | None = None,
) -> dict:
    """
    Run the single ICD-10 coding agent.
    Returns: { "result": str, "valid": bool, "thread_id": str }
    """
    tid = thread_id or f"session_{id(discharge_summary)}"
    rid = run_id or f"run_{uuid4().hex[:12]}"
    config: RunnableConfig = {"configurable": {"thread_id": tid}}
    last_output = ""
    context_tokens = bind_run_context(tid, rid)

    try:
        for attempt in range(max_retries):
            try:
                result = single_agent.invoke(
                    {"messages": [{"role": "user", "content": discharge_summary}]},
                    config=config,
                )
            except Exception as exc:
                last_output = f"⚠️ Invocation failed (attempt {attempt+1}): {exc}"
                continue

            # Extract the last non-empty AI message
            output = ""
            if isinstance(result, dict) and "messages" in result:
                for msg in reversed(result["messages"]):
                    content = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else None)
                    if content and str(content).strip():
                        output = str(content).strip()
                        break

            if not output:
                last_output = f"⚠️ Empty response (attempt {attempt+1})"
                continue

            last_output = output
            break  # Success, exit retry loop
    finally:
        reasoning = get_all_thought_text(rid)
        finalize_run(rid, persist_json=False)
        unbind_run_context(context_tokens)

    return {
        "result": last_output,
        "valid": not last_output.startswith("⚠️"),
        "thread_id": tid,
        "run_id": rid,
        "reasoning": reasoning,
    }

# Async wrapper for FastAPI
async def run_coding_agent_async(
    discharge_summary: str,
    thread_id: str | None = None,
    max_retries: int = 2,
    run_id: str | None = None,
) -> dict:
    from fastapi.concurrency import run_in_threadpool
    return await run_in_threadpool(run_coding_agent, discharge_summary, thread_id, max_retries, run_id)

# ============================================================
# 5. STARTUP STATUS
# ============================================================
print(f"🚀 ICD-10 Single Agent Ready")
print(f"   Model: {LLM_PROVIDER_STRING}")
print(f"   Timeout: {LLM_TIMEOUT}s | Max Retries: {LLM_MAX_RETRIES}")
print(f"   Persistence: {CHECKPOINT_DB}")
