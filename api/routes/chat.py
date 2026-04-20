from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import get_graph
from core.graph import Graph


# --- Schemas ---

class ChatRequest(BaseModel):
    user_id: str
    user_query: str


class ResumeRequest(BaseModel):
    thread_id: str
    # {interrupt_id: {question_text: selected_option_id}}
    answers: Dict[str, Dict[str, str]] = Field(
        ...,
        description="Map of interrupt_id to {question_text: answer}.",
    )


class ClarificationOption(BaseModel):
    id: str
    label: str


class ClarificationQuestion(BaseModel):
    id: str
    question: str
    options: List[ClarificationOption]


class Interrupt(BaseModel):
    id: str
    questions: List[ClarificationQuestion]


class ChatResponse(BaseModel):
    type: str  # "answer" or "clarification"
    answer: Optional[str] = None
    thread_id: Optional[str] = None
    interrupts: Optional[List[Interrupt]] = None


# --- Router ---

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


@router.post("/", response_model=ChatResponse)
def chat(body: ChatRequest, graph: Graph = Depends(get_graph)) -> ChatResponse:
    try:
        result = graph.run(body.user_id, body.user_query)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return _build_response(result)


@router.post("/resume", response_model=ChatResponse)
def resume(body: ResumeRequest, graph: Graph = Depends(get_graph)) -> ChatResponse:
    try:
        result = graph.resume(body.thread_id, body.answers)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return _build_response(result)


def _build_response(result: dict) -> ChatResponse:
    if result["type"] == "answer":
        return ChatResponse(type="answer", answer=result["content"])
    return ChatResponse(
        type="clarification",
        thread_id=result["thread_id"],
        interrupts=result["interrupts"],
    )
