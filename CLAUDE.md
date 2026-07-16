# AI_Agent — 사내 ERP 매출 데이터 분석 대화형 웹 시스템
## 스택: FastAPI / SQLAlchemy / MSSQL / Next.js

## 프로젝트 개요
사내 ERP 시스템의 MS-SQL 데이터베이스에 접속하여 매출 관련 데이터를 분석하는
대화형(챗봇) 웹 애플리케이션. 사용자가 자연어로 질문하면 AI 에이전트가 매출
관련 뷰(View)의 데이터를 조회하고, 엑셀 시트를 다루듯 집계·필터·비교 분석을
수행해 대화 형태로 답변한다.

## 핵심 아키텍처
- **대화 엔진**: Gemini (Gemini API)를 사용해 사용자와의 대화 및 분석 추론을 수행한다.
- **DB 연동**: MS-SQL Server에 MCP(Model Context Protocol) 서버를 통해 접속한다.
  에이전트가 직접 커넥션 문자열을 다루지 않고, MCP 서버가 노출하는 도구를 통해서만 쿼리를 실행한다.
- **접근 범위 제한(중요)**: 에이전트는 매출 관련 뷰(View)에만 접근 가능해야 한다.
  - 원본 테이블(Table)에는 직접 접근하지 않고, 매출 관련으로 사전 정의된 뷰만 대상으로 한다.
  - MCP 서버 단에서 접근 가능한 스키마/객체를 화이트리스트로 제한해야 한다 (뷰 목록 하드코딩 또는 별도 권한 계정 사용).
  - 매출 외 데이터(인사, 급여, 개인정보 등)가 포함된 테이블/뷰는 절대 조회 대상에 포함하지 않는다.
- **쿼리 방식**: 뷰 데이터를 엑셀 데이터처럼 취급 — 집계(GROUP BY), 필터(WHERE), 정렬, 기간 비교,
  피벗형 요약 등을 자연어 질의에 따라 SELECT 쿼리로 변환해 실행한다. 읽기 전용(SELECT-only)이며
  INSERT/UPDATE/DELETE/DDL은 허용하지 않는다.

## 보안 원칙
- DB 접속 계정은 최소 권한(해당 매출 뷰에 대한 SELECT만) 원칙을 따른다.
- SQL 인젝션 방지를 위해 파라미터화 쿼리를 사용하고, 사용자 입력을 직접 쿼리 문자열에 결합하지 않는다.
- MCP 서버 설정(접속 정보, 자격증명)은 저장소에 커밋하지 않고 환경변수/시크릿 매니저로 관리한다.
- 에이전트가 생성한 SQL은 실행 전에 허용된 뷰 목록/읽기 전용 여부를 검증하는 가드레일을 거친다.

## 개발 시 유의사항
- 새로운 매출 뷰를 추가할 때는 화이트리스트에 명시적으로 추가해야 하며, 기본값은 "접근 불가"로 둔다.
- 프론트엔드는 대화형 UI(챗봇 인터페이스)를 기본으로 하며, 표/차트 등 데이터 시각화 결과를 함께 보여줄 수 있다.

## Commands

Backend:
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # GEMINI_API_KEY, MSSQL_* 값 채우기
uvicorn app.main:app --reload --port 8000
```

Frontend:
```bash
cd frontend
npm install
npm run dev   # http://localhost:3000
```

정식 테스트 러너는 없음. 임시 점검용 스크립트: `backend/scripts/test_db_connection.py`,
`backend/scripts/test_mcp_client.py`, `backend/scripts/test_chat_err.py` — 백엔드 venv의 python으로
`python -m backend.scripts.test_mcp_client` 형태로 직접 실행한다.

ODBC Driver 18 for SQL Server가 로컬에 설치되어 있어야 한다.

## 아키텍처 (구현 기준)

요청 흐름: 브라우저 → Next.js rewrite (`frontend/next.config.js`, `/api/*` → `BACKEND_URL`/api/*,
기본값 `http://localhost:8000`) → FastAPI `/api/chat` ([backend/app/main.py](backend/app/main.py)) →
`run_chat()` ([backend/app/gemini_agent.py](backend/app/gemini_agent.py)).

**MCP 세션은 요청(대화 1턴)마다 새로 열고 닫는다.** `run_chat()`이 매 턴마다 `McpSalesClient`
([backend/app/mcp_client.py](backend/app/mcp_client.py))를 새로 열고 `finally`에서 닫는다. 이는 의도된
설계다 — 세션을 앱 전체에서 공유하면 동시 채팅 요청이 같은 stdio 파이프를 두고 경합해 서로의 도구 호출을
직렬화시킨다. mcp_client.py의 주석을 다시 확인하지 않고 이 부분을 공유/풀링 세션으로 "최적화"하지 말 것.

**Gemini 도구 호출 루프.** `gemini_agent.py`는 MCP 서버의 도구 목록을 Gemini `FunctionDeclaration`으로
변환한 뒤, `generate_content` 호출 → `function_call` 실행(MCP 세션에 위임) → 결과를 `function_response`로
피드백하는 루프를 최대 `MAX_TOOL_ROUNDS = 6`회 반복하다가, Gemini가 텍스트만 반환하면 종료한다.
시스템 프롬프트(`SYSTEM_PROMPT`, [backend/app/config.py](backend/app/config.py))는 Gemini에게 SQL 작성
전 `get_view_aliases`/`get_column_aliases`로 한글 별칭을 실제 이름으로 해석하도록 지시하고, 추이/비교
분석 시 프론트엔드 `ChartRenderer.tsx`가 파싱하는 ```chart``` JSON 블록을 함께 출력하도록 지시한다.

**DB 자격증명은 MCP 서버 프로세스만 보유한다.** `python -m backend.mcp_server.server`로 실행되는 stdio
서브프로세스이며, `mcp_client.py`가 부모 프로세스의 전체 환경변수를 명시적으로 전달한다 (MCP 기본
서브프로세스 환경은 OS 화이트리스트만 상속하므로 `MSSQL_*`/`GEMINI_*`가 전달되지 않는다). 노출 도구는
정확히 5개: `list_sales_views`, `get_view_schema`, `get_view_aliases`, `get_column_aliases`, `run_sql`.

**접근 통제는 다단계이며 기본값은 거부다:**
1. [backend/mcp_server/views_whitelist.py](backend/mcp_server/views_whitelist.py) — `SALES_VIEW_WHITELIST`가
   조회 가능한 `schema.view`의 단일 소스다. 새 매출 뷰 추가는 여기만 수정하면 된다. 이 파일은 한글 별칭
   테이블(`VIEW_ALIASES`, `COLUMN_ALIASES`)과 `rewrite_query_with_aliases()`도 갖고 있으며, sql_guard 검증
   전에 SQL 문자열 내 한글 별칭을 실제 뷰/컬럼명으로 치환한다.
2. [backend/mcp_server/sql_guard.py](backend/mcp_server/sql_guard.py) — `validate_and_prepare()`는 별칭
   치환 이후 실행된다: 다중 문장(`;`) 차단, SELECT 이외 차단, 금지 키워드(DML/DDL, `xp_cmdshell`,
   `sp_executesql`, `OPENROWSET` 등) 차단, 모든 `FROM`/`JOIN` 대상을 화이트리스트와 대조, `TOP` 절이 없으면
   `TOP 1000` 자동 삽입. 이 가드를 수정할 때는 (별칭 치환 → 키워드 검사 → 테이블 참조 검사 → 행수 제한)
   전체 파이프라인 관점에서 우회 가능성을 검토해야 하며, 정규식 하나만 보고 판단하지 말 것.
3. [backend/mcp_server/db.py](backend/mcp_server/db.py) — `MSSQL_READONLY_USER`가 화이트리스트 뷰에 대해서만
   SELECT 권한을 가진 DB 계정이라고 전제한다; 앱 코드가 이를 강제하지는 않으며 운영상 전제조건이다.

이 세 파일은 defense-in-depth 체인이다 — 하나(예: sql_guard.py의 정규식 완화)를 느슨하게 바꾸면 나머지가
가정하는 보장이 조용히 깨질 수 있다는 점을 유의한다.

## 프론트엔드 참고

- `frontend/components/Chat.tsx`는 `react-markdown`으로 assistant 메시지를 렌더링하며, `language-chart`
  태그가 붙은 코드 블록을 가로채 `frontend/components/ChartRenderer.tsx`의 `parseChartSpec`으로 전달한다.
- `next.config.js`는 `experimental.proxyTimeout: 120_000`을 설정한다 — 챗 요청 1턴에 Gemini 왕복 여러 번과
  DB 쿼리가 포함되어 Next의 기본 30초 rewrite-proxy 타임아웃을 넘길 수 있기 때문이다.

