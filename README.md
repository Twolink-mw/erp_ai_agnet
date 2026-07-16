# ERP 매출 분석 챗봇

사내 ERP MS-SQL 데이터베이스의 매출 관련 뷰(View)에만 접근하여, Gemini와의
대화를 통해 엑셀 시트를 분석하듯 매출 데이터를 조회/집계/비교하는 웹 시스템.

## 구조

```
backend/
  mcp_server/        # MSSQL 매출 뷰 전용 MCP 서버 (stdio)
    views_whitelist.py  # 접근 가능한 뷰 화이트리스트
    sql_guard.py        # LLM 생성 SQL 검증 (SELECT-only, 화이트리스트, 행수 제한)
    db.py               # SQLAlchemy/pyodbc 읽기 전용 커넥션
    server.py           # MCP 도구 정의: list_sales_views / get_view_schema / run_sql
  app/               # FastAPI 백엔드
    main.py             # /api/chat, MCP 클라이언트 생명주기
    gemini_agent.py      # Gemini function-calling 루프 (MCP 도구를 Gemini 도구로 브릿지)
    mcp_client.py         # MCP 서버 서브프로세스에 대한 stdio 클라이언트
    config.py             # 환경변수, 시스템 프롬프트
frontend/            # Next.js 챗 UI
```

## 데이터 접근 통제

1. `views_whitelist.py`에 명시된 `schema.view`만 조회 가능 (기본값: 접근 불가).
2. `sql_guard.py`가 Gemini가 생성한 SQL을 실행 전에 검증:
   - SELECT 단일 문장만 허용, 세미콜론으로 이어진 다중 문장 차단
   - INSERT/UPDATE/DELETE/DROP 등 DML/DDL 및 위험 키워드 차단
   - FROM/JOIN 대상이 화이트리스트 뷰인지 확인
   - TOP 절이 없으면 자동으로 최대 1000행 제한 삽입
3. DB 접속 계정은 해당 뷰에 대한 SELECT 권한만 가진 전용 계정 사용을 전제로 함.

## 실행 방법

### 1. MS-SQL 준비
- 매출 관련 뷰를 생성하고 `backend/mcp_server/views_whitelist.py`에 등록
- 해당 뷰에 대해서만 SELECT 권한을 가진 전용 로그인 계정 생성

### 2. 백엔드

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # 값 채우기 (GEMINI_API_KEY, MSSQL_* )
uvicorn app.main:app --reload --port 8000
```

### 3. 프론트엔드

```bash
cd frontend
npm install
npm run dev
```

브라우저에서 http://localhost:3000 접속.

## 참고
- ODBC Driver 18 for SQL Server가 설치되어 있어야 함.
- Gemini 모델은 `backend/.env`의 `GEMINI_MODEL`로 지정 (기본 `gemini-2.5-flash`).
- 새 매출 뷰 추가 시 `views_whitelist.py`에만 등록하면 되고, 별도 코드 변경은 필요 없음.
