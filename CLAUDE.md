# AI_Agent — 사내 ERP 매출 데이터 분석 챗봇

## 문서 목적
이 문서는 새 세션에서 프로젝트를 빠르게 이해하고, 안전하게 변경할 수 있도록 돕기 위한 개발자용 참고 문서입니다.

## 작업 우선순위
1. 보안 규칙을 먼저 확인한다.
2. 사용자 요청이 어떤 계층을 거치는지 파악한다.
3. 변경 범위가 백엔드/프론트엔드/보안 가드 중 어디에 영향을 주는지 확인한다.
4. 기존 계약(도구 스펙, 응답 포맷, UI 파싱 방식)을 깨지 않도록 최소 변경으로 진행한다.

## 시스템 개요
이 프로젝트는 자연어 질의 → SQL 조회 → 결과 반환 흐름으로 동작하는 ERP 매출 분석 챗봇입니다.

- 프론트엔드: Next.js 기반 챗 UI
- 백엔드: FastAPI + Gemini 에이전트
- 데이터 계층: MCP 서버를 통한 SQL 실행
- 보안 계층: 뷰 화이트리스트 + SQL 가드

## 요청 흐름
사용자 질문 → Next.js → FastAPI → Gemini 에이전트 → MCP 서버 → SQL 실행 → 결과 반환

## 주요 모듈과 역할
- [backend/app/main.py](backend/app/main.py): FastAPI 엔드포인트(`/api/chat`, `/api/report/pdf`, `/api/report/email`, `/api/report/email/presets`), API 요청 처리
- [backend/app/gemini_agent.py](backend/app/gemini_agent.py): Gemini 함수 호출 루프, MCP 도구 실행 오케스트레이션. 도구 미호출 데이터 환각/코드 블록 응답을 감지해 제한적으로 재시도하는 그라운딩 체크 포함
- [backend/app/mcp_client.py](backend/app/mcp_client.py): MCP 클라이언트 세션 생성/종료 관리
- [backend/app/config.py](backend/app/config.py): 시스템 프롬프트 및 에이전트 설정, 이메일 관련 환경변수(SMTP_*, ALLOWED_EMAIL_DOMAINS, EMAIL_PRESET_RECIPIENTS)
- [backend/app/pdf_report.py](backend/app/pdf_report.py): 챗봇 응답을 PDF로 렌더링(순수 렌더링 계층, DB/MCP 접근 없음)
- [backend/app/mailer.py](backend/app/mailer.py): PDF 리포트를 SMTP로 발송(순수 발송 계층, DB/MCP 접근 없음)
- [backend/mcp_server/server.py](backend/mcp_server/server.py): MCP stdio 서버 진입점
- [backend/mcp_server/views_whitelist.py](backend/mcp_server/views_whitelist.py): 허용된 매출 뷰, 별칭 매핑, 쿼리 치환
- [backend/mcp_server/sql_guard.py](backend/mcp_server/sql_guard.py): SQL 검증, 읽기 전용 제한, 금지 패턴 검사. CTE(`WITH`)는 정식 지원됨(화이트리스트 밖 테이블을 CTE 안에 숨기는 시도만 차단 대상)
- [backend/mcp_server/db.py](backend/mcp_server/db.py): DB 연결 및 권한 전제
- [frontend/components/Chat.tsx](frontend/components/Chat.tsx): 챗봇 UI 렌더링, PDF 다운로드/이메일 발송 버튼, 순위 변동(▲/▼) 셀 색상
- [frontend/components/ChartRenderer.tsx](frontend/components/ChartRenderer.tsx): 차트/표 파싱 및 렌더링
- [frontend/app/layout.tsx](frontend/app/layout.tsx): 전역 테마 CSS 변수(라이트/다크 토큰)

## 구현 시 반드시 지켜야 할 규칙
- 새 매출 뷰는 반드시 화이트리스트에 등록해야 한다.
- SQL은 SELECT만 허용해야 한다.
- INSERT, UPDATE, DELETE, DDL은 금지된다.
- 사용자 입력을 직접 SQL 문자열에 결합하지 않는다.
- 보안 가드나 화이트리스트를 변경할 때는 전체 보안 흐름을 함께 검토한다.
- MCP 세션은 요청마다 새로 열고 닫는 구조를 유지한다.
- 차트 결과는 프론트엔드가 파싱 가능한 형식으로 반환해야 한다.
- PDF 렌더링(`pdf_report.py`)과 이메일 발송(`mailer.py`)은 순수 렌더링/발송 계층이다 — 새 SQL 실행이나
  MCP 세션을 열지 않는다. 데이터는 항상 `/api/chat`이 이미 반환한 응답을 그대로 받아서만 쓴다.
- 이메일 수신자는 `ALLOWED_EMAIL_DOMAINS` 화이트리스트 검증을 항상 거친다 — `EMAIL_PRESET_RECIPIENTS`에
  있는 주소라도 이 검증을 우회하지 않는다.

## 개발 체크리스트
- 변경이 백엔드, 프론트엔드, 또는 보안 가드 중 어디에 영향을 주는지 확인한다.
- 기존 API/도구 스펙과 프론트엔드 파싱 계약이 깨지지 않는지 검토한다.
- 관련 테스트 또는 점검 스크립트를 실행한다.
- 보안 위반 가능성이 없는지 최종 확인한다.
- **동작/설정값(라운드 수, 타임아웃, 신규 파일·엔드포인트·환경변수 등)을 바꿨다면, 그 값을
  언급하는 `.claude/agents/*.md`와 `.claude/skills/*/SKILL.md`도 같이 갱신했는지 확인한다** —
  안 그러면 문서가 실제 코드와 어긋난 채로 쌓여(드리프트) 다음 세션이 잘못된 값을 참고하게 된다.
  값이 하드코딩된 곳을 놓치지 않으려면 바뀐 값(예: 이전 숫자)을 `grep -rn` 해서 `.claude/` 안에
  남은 참조가 없는지 확인하는 게 빠르다.

## 실행 방법
### 1) 준비 사항
- Python 환경
- Node.js 환경
- ODBC Driver 18 for SQL Server 설치
- backend/.env에 GEMINI_API_KEY, MSSQL_* 값 설정

### 2) 백엔드 실행
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
if not exist .env copy .env.example .env
cd ..
uvicorn backend.app.main:app --reload --port 8000
```
> **주의:** 마지막 `uvicorn` 실행은 반드시 워크스페이스 루트([d:\WebDev\AI_Agent](d:\WebDev\AI_Agent))에서 해야 한다.
> [backend/app/mcp_client.py](backend/app/mcp_client.py)가 MCP 서버를 `python -m backend.mcp_server.server`로 서브프로세스 실행하는데,
> `backend/` 안에서 uvicorn을 띄우면(cwd가 `backend/`가 되면) `backend` 패키지를 찾지 못해
> `ModuleNotFoundError: No module named 'backend'`로 MCP 연결이 실패하고 챗봇에 "도구 연결 실패" 메시지가 뜬다.
>
> **주의:** `copy .env.example .env`는 `.env`가 이미 있으면 **확인 없이 덮어쓴다** — 이미 설정해둔
> GEMINI_API_KEY/MSSQL_*/SMTP_* 값이 통째로 플레이스홀더로 날아간다. 위 명령은 `.env`가 없을 때만
> 복사하도록 가드를 넣었으니, 이미 `.env`가 있는 상태라면 이 단계 전체를 건너뛸 것. 실수로 덮어썼다면
> git에는 `.env`가 추적되지 않으므로(.gitignore) 복구가 안 되고, VS Code를 쓴다면
> `%APPDATA%\Code\User\History\`의 Local History 스냅샷이 유일한 복구 경로일 수 있다.

### 3) 프론트엔드 실행
```bash
cd frontend
npm install
npm run dev
```

### 4) 접속
- 브라우저에서 http://localhost:3000 접속
- 프론트엔드는 /api/* 요청을 백엔드로 전달한다.

## 점검용 스크립트
- [backend/scripts/test_db_connection.py](backend/scripts/test_db_connection.py)
- [backend/scripts/test_mcp_client.py](backend/scripts/test_mcp_client.py)
- [backend/scripts/test_chat_err.py](backend/scripts/test_chat_err.py)

## 작업 시 주의할 점
- 이 프로젝트는 보안이 가장 중요한 제약 조건이다.
- 기능 추가보다 기존 구조와 보안 규칙을 유지하는 것이 우선이다.
- 가드레일을 우회하는 방식으로 변경하지 않는다.

## 하네스: 사내 ERP 매출 챗봇 개발

**목표:** mcp_server(보안 가드레일) / app(Gemini 에이전트 루프) / frontend(챗 UI) 3개 계층에 걸친
개발 작업을, 계층별 전문 에이전트(mcp-guardian / backend-dev / frontend-dev)와 검증 에이전트
(qa-verifier)로 분담해 경계면 불일치 없이 진행한다.

**트리거:** 새 매출 뷰/화이트리스트/SQL 가드 수정, Gemini 에이전트 루프/시스템 프롬프트 변경,
챗봇 UI/차트 개선, PDF/이메일 리포트 기능 변경 등 위 3개 계층 중 하나 이상을 건드리는 개발
작업 요청 시 `erp-sales-harness` 스킬을 사용하라. 이전 변경 보완/재검증/부분 수정 같은 후속
요청에도 마찬가지다. 단순 질문이나 조사는 직접 응답 가능.

**변경 이력:**
| 날짜 | 변경 내용 | 대상 | 사유 |
|------|----------|------|------|
| 2026-08-21 | 하네스 포인터 최초 등록 + 에이전트/스킬 정의 실제 코드와 동기화(`MAX_TOOL_ROUNDS` 6→10, `proxyTimeout` 120s→240s, `mailer.py`/`pdf_report.py`/PDF·이메일 엔드포인트/환경변수 반영, CTE 지원 반영, 그라운딩 체크/코드 덤프 방지 로직 반영) | agents/backend-dev.md, agents/frontend-dev.md, agents/mcp-guardian.md, skills/erp-integration-qa, skills/sql-guardrail-review, skills/gemini-agent-dev | 문서-코드 드리프트 발견(개발 누적 후 문서 미갱신) |

## 직접 서비스 실행 방법
1) 백엔드 실행 (터미널 1개, 반드시 워크스페이스 루트 d:\WebDev\AI_Agent에서)
cd d:\WebDev\AI_Agent
backend\.venv\Scripts\activate
uvicorn backend.app.main:app --reload --port 8000

주의: backend\ 폴더 안에서 uvicorn을 띄우면 안 됩니다 — MCP 서버 서브프로세스가 backend 패키지를 못 찾아 "도구 연결 실패"가 뜹니다.
정상이면 Uvicorn running on http://127.0.0.1:8000 로그가 뜨고 에러 없이 유지됩니다.

2) 프론트엔드 실행 (별도 터미널)

cd d:\WebDev\AI_Agent\frontend
npm run dev

http://localhost:3000에서 서비스 시작 로그가 뜹니다.

## 직접 서비스 종료 방법
1) 프론트엔드 종료
npm run dev가 실행 중인 터미널 창에서 Ctrl + C


2) 백엔드 종료
uvicorn이 실행 중인 터미널 창에서 Ctrl + C
--reload 옵션 때문에 워커 프로세스가 자식으로 떠 있을 수 있는데, Ctrl+C 한 번이면 보통 같이 종료됩니다. 혹시 터미널을 닫았는데도 포트가 계속 잡혀있으면 아래로 확인/정리하시면 됩니다.

# 8000번 포트를 쓰는 프로세스 확인
netstat -ano | findstr :8000
# 나온 PID로 강제 종료
taskkill /PID <해당PID> /F