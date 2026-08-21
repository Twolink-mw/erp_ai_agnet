import logging
import sys
import asyncio

# Windows에서 subprocess를 사용하려면 ProactorEventLoopPolicy가 필요합니다.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from urllib.parse import quote

from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import config, mailer
from .gemini_agent import run_chat
from .config import CORS_ALLOW_ORIGINS
from .pdf_report import (
    DEFAULT_TITLE,
    PdfReportRequest,
    build_pdf,
    has_reportable_content,
    safe_filename,
)

# 도구 호출/그라운딩 경고 로그(gemini_agent)가 stderr로 나가도록 root 로거를
# 1회 초기화한다. 로컬 실행 시 uvicorn stderr 리다이렉트 파일에서 확인 가능.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# MCP 세션은 요청(대화 1턴)마다 run_chat()이 새로 열고 닫는다 — 동시 채팅
# 요청이 하나의 stdio 세션을 두고 경합해 서로를 직렬화시키는 걸 막기 위함.
app = FastAPI(title="ERP 매출 분석 챗봇")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    # PDF 다운로드 시 브라우저 fetch가 파일명을 읽을 수 있어야 한다.
    expose_headers=["Content-Disposition"],
)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


class ChatResponse(BaseModel):
    reply: str
    tool_calls: list[dict]
    # 옵셔널 확장 필드 — 기존 프론트 계약을 깨지 않는다.
    # 응답에 표/차트가 있어 PDF 리포트로 만들 만한지에 대한 힌트.
    report_available: bool = False


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    result = await run_chat([m.model_dump() for m in req.messages])
    result.setdefault("report_available", has_reportable_content(result.get("reply", "")))
    return ChatResponse(**result)


@app.post("/api/report/pdf")
async def report_pdf(req: PdfReportRequest) -> Response:
    """이미 받은 챗봇 응답을 PDF로 렌더링한다.

    새 SQL 실행도, 매출 뷰 접근도 하지 않는 순수 렌더링 엔드포인트다 —
    데이터는 전부 요청 본문으로 들어온다.
    """
    try:
        pdf_bytes = build_pdf(req)
    except Exception:
        # 내부 경로/스택은 노출하지 않는다.
        raise HTTPException(status_code=500, detail="PDF 생성에 실패했습니다.")

    name = safe_filename(req.filename or req.title)
    ascii_fallback = name.encode("ascii", "ignore").decode() or "sales_report.pdf"
    disposition = (
        f'attachment; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{quote(name)}"
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": disposition,
            "Content-Length": str(len(pdf_bytes)),
            "Cache-Control": "no-store",
        },
    )


class EmailReportRequest(PdfReportRequest):
    to: list[str] = Field(default_factory=list)


class EmailPresetsResponse(BaseModel):
    presets: list[str] = Field(default_factory=list)


@app.get("/api/report/email/presets", response_model=EmailPresetsResponse)
async def report_email_presets() -> EmailPresetsResponse:
    """자주 쓰는 수신자 주소 추천 목록을 돌려준다.

    발송 UI가 항상 안전하게 호출할 수 있도록, 이메일 기능이 비활성(SMTP_HOST/
    ALLOWED_EMAIL_DOMAINS 미설정) 상태여도 503을 내지 않고 200 + 빈 리스트를 준다.
    이 목록은 "추천"일 뿐이며 발송 허용 여부는 여전히 /api/report/email의
    ALLOWED_EMAIL_DOMAINS 검증이 전담한다 — 프리셋만 허용하도록 제한하지 않는다.
    """
    return EmailPresetsResponse(presets=list(config.EMAIL_PRESET_RECIPIENTS))


@app.post("/api/report/email")
async def report_email(req: EmailReportRequest) -> dict:
    """이미 받은 챗봇 응답을 PDF로 렌더링해 사내 도메인 수신자에게 이메일로 보낸다.

    /api/report/pdf와 마찬가지로 새 SQL 실행도, 매출 뷰 접근도 하지 않는
    순수 엔드포인트다 — 데이터는 전부 요청 본문으로 들어온다.
    """
    if not config.SMTP_HOST or not config.ALLOWED_EMAIL_DOMAINS:
        raise HTTPException(status_code=503, detail="이메일 발송 기능이 설정되지 않았습니다.")

    try:
        recipients = mailer.validate_recipients(req.to)
    except mailer.EmailDomainNotAllowedError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        pdf_bytes = build_pdf(req)
    except Exception:
        # 내부 경로/스택은 노출하지 않는다.
        raise HTTPException(status_code=500, detail="PDF 생성에 실패했습니다.")

    filename = safe_filename(req.filename or req.title)
    title = req.title or DEFAULT_TITLE
    body_lines = [
        f"질문: {req.question}" if req.question else None,
        f"생성 시각: {req.generated_at or datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "첨부된 PDF를 확인하세요.",
    ]
    payload = mailer.EmailReportPayload(
        to=recipients,
        subject=f"[ERP 매출 리포트] {title}",
        body_text="\n".join(line for line in body_lines if line is not None),
        pdf_bytes=pdf_bytes,
        pdf_filename=filename,
    )

    try:
        mailer.send_email(payload)
    except mailer.EmailSendError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return {"status": "sent", "to": recipients}


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
