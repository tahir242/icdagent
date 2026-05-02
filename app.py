from datetime import datetime
from typing import Optional

import asyncio
import json
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.utils.uuid import uuid7
from pydantic import BaseModel

from agent import run_coding_agent, run_coding_agent_async
from memory import client
from project_paths import EXPORTS_DIR, ensure_runtime_dirs
from session_store import (
    add_message,
    create_thread,
    delete_thread,
    ensure_thread_exists,
    get_thread,
    init_session_db,
    list_messages,
    list_threads,
    update_thread,
)
from thinking_runtime import get_new_thoughts
from tools import save_correction_api

ensure_runtime_dirs()
init_session_db()

app = FastAPI(title="ICD-10 Learning Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _default_thread_title(text: str) -> str:
    cleaned = " ".join((text or "").strip().split())
    if not cleaned:
        return "New Session"
    return cleaned[:60] + ("..." if len(cleaned) > 60 else "")


class CodingRequest(BaseModel):
    discharge_summary: str
    thread_id: Optional[str] = None


class CorrectionRequest(BaseModel):
    snippet: str
    wrong_code: str
    correct_code: str
    explanation: str = ""


class BatchRequest(BaseModel):
    summaries: list[str]


class ThreadCreateRequest(BaseModel):
    title: Optional[str] = "New Session"


class ThreadUpdateRequest(BaseModel):
    title: Optional[str] = None
    updated_at: Optional[str] = None


@app.post("/threads")
async def create_thread_endpoint(req: ThreadCreateRequest = ThreadCreateRequest()):
    title = req.title or "New Session"
    return await run_in_threadpool(create_thread, title, None)


@app.get("/threads")
async def list_threads_endpoint(limit: int = 50, offset: int = 0):
    items = await run_in_threadpool(list_threads, limit, offset)
    return {"threads": items}


@app.get("/threads/{thread_id}")
async def get_thread_endpoint(thread_id: str):
    try:
        return await run_in_threadpool(get_thread, thread_id, True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/threads/{thread_id}/messages")
async def get_thread_messages_endpoint(thread_id: str):
    try:
        await run_in_threadpool(get_thread, thread_id, True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    messages = await run_in_threadpool(list_messages, thread_id)
    return {"thread_id": thread_id, "messages": messages}


@app.patch("/threads/{thread_id}")
async def update_thread_endpoint(thread_id: str, req: ThreadUpdateRequest):
    try:
        return await run_in_threadpool(update_thread, thread_id, req.title, req.updated_at)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/threads/{thread_id}")
async def delete_thread_endpoint(thread_id: str):
    deleted = await run_in_threadpool(delete_thread, thread_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Thread not found.")
    return {"status": "deleted", "thread_id": thread_id}


@app.post("/code")
async def code_procedure(req: CodingRequest):
    summary = (req.discharge_summary or "").strip()
    if not summary:
        raise HTTPException(status_code=400, detail="discharge_summary cannot be empty.")

    thread_title = _default_thread_title(summary)
    if req.thread_id:
        thread = await run_in_threadpool(ensure_thread_exists, req.thread_id, thread_title)
    else:
        thread = await run_in_threadpool(create_thread, thread_title, None)

    thread_id = thread["id"]
    await run_in_threadpool(add_message, thread_id, "user", summary, None, datetime.now().isoformat())

    try:
        result = await asyncio.wait_for(
            run_in_threadpool(run_coding_agent, summary, thread_id),
            timeout=600,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Coding request timed out.") from exc

    assistant_ts = datetime.now().isoformat()
    assistant_msg = await run_in_threadpool(
        add_message,
        thread_id,
        "assistant",
        result.get("result", ""),
        result.get("reasoning", []),
        assistant_ts,
    )

    return {
        "result": result["result"],
        "valid": result["valid"],
        "thread_id": thread_id,
        "timestamp": assistant_msg["timestamp"],
        "reasoning": assistant_msg["reasoning"],
        "icd_codes": [],
        "pcs_codes": [],
    }


@app.post("/code/stream")
async def code_procedure_stream(req: CodingRequest):
    summary = (req.discharge_summary or "").strip()
    if not summary:
        raise HTTPException(status_code=400, detail="discharge_summary cannot be empty.")

    thread_title = _default_thread_title(summary)
    if req.thread_id:
        thread = await run_in_threadpool(ensure_thread_exists, req.thread_id, thread_title)
    else:
        thread = await run_in_threadpool(create_thread, thread_title, None)

    thread_id = thread["id"]
    await run_in_threadpool(add_message, thread_id, "user", summary, None, datetime.now().isoformat())

    async def event_generator():
        run_id = f"run_{uuid7().hex[:12]}"
        cursor = 0
        started = asyncio.get_running_loop().time()
        deadline_seconds = 900

        yield f"data: {json.dumps({'type': 'status', 'status': 'processing', 'thread_id': thread_id, 'run_id': run_id})}\n\n"

        task = asyncio.create_task(run_coding_agent_async(summary, thread_id=thread_id, run_id=run_id))

        try:
            while not task.done():
                if asyncio.get_running_loop().time() - started > deadline_seconds:
                    task.cancel()
                    raise asyncio.TimeoutError

                new_thoughts, cursor = get_new_thoughts(run_id, cursor)
                for thought in new_thoughts:
                    payload = {
                        "type": "thinking",
                        "thread_id": thread_id,
                        "run_id": run_id,
                        "thought": thought["thought"],
                        "timestamp": thought["timestamp"],
                    }
                    yield f"data: {json.dumps(payload)}\n\n"

                await asyncio.sleep(0.15)

            # Final flush in case any thoughts arrived right before task completion.
            new_thoughts, cursor = get_new_thoughts(run_id, cursor)
            for thought in new_thoughts:
                payload = {
                    "type": "thinking",
                    "thread_id": thread_id,
                    "run_id": run_id,
                    "thought": thought["thought"],
                    "timestamp": thought["timestamp"],
                }
                yield f"data: {json.dumps(payload)}\n\n"

            result = await task
            assistant_ts = datetime.now().isoformat()
            assistant_msg = await run_in_threadpool(
                add_message,
                thread_id,
                "assistant",
                result.get("result", ""),
                result.get("reasoning", []),
                assistant_ts,
            )

            payload = {
                "type": "result",
                "thread_id": thread_id,
                "run_id": run_id,
                "result": assistant_msg["content"],
                "reasoning": assistant_msg["reasoning"],
                "timestamp": assistant_msg["timestamp"],
                "valid": result.get("valid", True),
            }
            yield f"data: {json.dumps(payload)}\n\n"

        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'type': 'error', 'error': 'Request timed out.'})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"
        finally:
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/batch")
async def batch_code(req: BatchRequest):
    results = []
    for idx, summary in enumerate(req.summaries):
        cleaned_summary = (summary or "").strip()
        if not cleaned_summary:
            raise HTTPException(
                status_code=400,
                detail=f"summaries[{idx}] cannot be empty.",
            )
        try:
            res = await asyncio.wait_for(
                run_in_threadpool(run_coding_agent, cleaned_summary),
                timeout=150,
            )
        except asyncio.TimeoutError as exc:
            raise HTTPException(status_code=504, detail="Batch coding request timed out.") from exc
        results.append(res)
    return {"results": results}


@app.post("/correct")
async def save_correction(req: CorrectionRequest):
    message = await run_in_threadpool(
        save_correction_api, req.snippet, req.wrong_code, req.correct_code, req.explanation
    )
    return {"status": "success", "message": message}


@app.get("/lessons")
async def get_lessons_dashboard():
    collection = client.get_or_create_collection("coding_corrections")
    data = collection.get()
    df = pd.DataFrame(
        {
            "snippet": data["documents"],
            "wrong": [m["wrong"] for m in data["metadatas"]],
            "correct": [m["correct"] for m in data["metadatas"]],
            "explanation": [m.get("explanation", "") for m in data["metadatas"]],
        }
    )
    return {"total_lessons": len(df), "data": df.to_dict(orient="records")}


@app.get("/lessons/export")
async def export_lessons():
    collection = client.get_or_create_collection("coding_corrections")
    data = collection.get()
    df = pd.DataFrame(
        {
            "snippet": data["documents"],
            "wrong": [m["wrong"] for m in data["metadatas"]],
            "correct": [m["correct"] for m in data["metadatas"]],
            "explanation": [m.get("explanation", "") for m in data["metadatas"]],
        }
    )
    export_file = EXPORTS_DIR / "lessons_export.csv"
    df.to_csv(export_file, index=False)
    return {"download_url": f"/runtime/exports/{export_file.name}"}


@app.get("/health")
async def health():
    return {"status": "ok"}
