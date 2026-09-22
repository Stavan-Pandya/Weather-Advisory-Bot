"""FastAPI backend for the React chat frontend.

Thin wrapper: builds the graph once at process start and exposes a single
chat endpoint. All the actual logic (SOP matching, grounding, failure
handling) lives in graph.py -- this file has none of it.
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from app.graph import build_graph, run_turn  # noqa: E402

app = FastAPI(title="Weather-Advisory Support Bot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

GRAPH = build_graph()


class ChatRequest(BaseModel):
    thread_id: str
    message: str


class ChatResponse(BaseModel):
    final_answer: str
    matched_sop_id: str | None = None
    error_stage: str | None = None


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    result = run_turn(GRAPH, req.thread_id, req.message)
    return ChatResponse(
        final_answer=result["final_answer"],
        matched_sop_id=result.get("matched_sop_id"),
        error_stage=result.get("error_stage"),
    )


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
