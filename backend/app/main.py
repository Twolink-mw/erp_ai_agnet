import sys
import asyncio

# Windows에서 subprocess를 사용하려면 ProactorEventLoopPolicy가 필요합니다.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .gemini_agent import run_chat
from .config import CORS_ALLOW_ORIGINS

# MCP 세션은 요청(대화 1턴)마다 run_chat()이 새로 열고 닫는다 — 동시 채팅
# 요청이 하나의 stdio 세션을 두고 경합해 서로를 직렬화시키는 걸 막기 위함.
app = FastAPI(title="ERP 매출 분석 챗봇")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


class ChatResponse(BaseModel):
    reply: str
    tool_calls: list[dict]


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    result = await run_chat([m.model_dump() for m in req.messages])
    return ChatResponse(**result)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
