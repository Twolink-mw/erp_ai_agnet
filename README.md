# ERP 매출 분석 챗봇

이 서비스는 사내 ERP의 MS-SQL 데이터베이스에 저장된 매출 데이터를, 자연어로 조회하고 분석할 수 있게 해주는 웹 애플리케이션입니다. 사용자가 질문을 입력하면 AI 에이전트가 SQL을 생성해 허용된 매출 뷰를 조회하고, 결과를 챗봇 응답과 차트 형태로 제공합니다.

## 서비스 개요

이 시스템은 다음 목적을 갖습니다.

- 사용자가 자연어로 매출 데이터를 조회하고 요약할 수 있도록 지원한다.
- 원본 테이블에 직접 접근하지 않고, 사전에 승인된 매출 뷰만 사용하도록 제한한다.
- 읽기 전용 쿼리만 허용해 안전하게 운영한다.

## 시스템 구성

서비스는 다음 구성으로 운영됩니다.

- 프론트엔드: Next.js 기반 챗봇 UI
- 백엔드: FastAPI 기반 API 서버
- AI 처리: Gemini 에이전트가 도구 호출을 통해 데이터 조회
- 데이터 계층: MCP 서버를 통해 MS-SQL에 접근
- 보안 계층: 뷰 화이트리스트와 SQL 가드로 접근 제어

## 주요 처리 흐름

사용자의 질문은 아래 순서로 처리됩니다.

1. 사용자가 프론트엔드에 질문을 입력한다.
2. Next.js가 백엔드 API로 요청을 전달한다.
3. FastAPI가 Gemini 에이전트에 요청을 위임한다.
4. Gemini가 MCP 서버의 도구를 호출해 SQL을 실행한다.
5. 결과를 챗 응답, 표, 차트 형태로 사용자에게 반환한다.

## 운영 포인트

운영자는 다음 항목을 우선 점검해야 합니다.

- 서비스 정상 여부: 백엔드 서버, 프론트엔드 서버, MCP 연동 상태
- 데이터 접근 상태: 허용된 뷰를 통해 정상 조회되는지
- 보안 상태: 화이트리스트와 SQL 가드가 정상 동작하는지
- 외부 연동 상태: Gemini API와 MS-SQL 연결 상태

## 주요 모듈

- [backend/app/main.py](backend/app/main.py): FastAPI 엔드포인트 및 API 처리
- [backend/app/gemini_agent.py](backend/app/gemini_agent.py): Gemini 함수 호출 루프 및 MCP 도구 실행
- [backend/app/mcp_client.py](backend/app/mcp_client.py): MCP 서버와의 세션 관리
- [backend/app/config.py](backend/app/config.py): 환경변수 및 시스템 프롬프트 설정
- [backend/mcp_server/views_whitelist.py](backend/mcp_server/views_whitelist.py): 허용된 매출 뷰와 별칭 처리
- [backend/mcp_server/sql_guard.py](backend/mcp_server/sql_guard.py): SQL 검증 및 읽기 전용 제한
- [backend/mcp_server/db.py](backend/mcp_server/db.py): MS-SQL 연결 및 권한 전제
- [backend/mcp_server/server.py](backend/mcp_server/server.py): MCP 서버 진입점 및 도구 정의
- [frontend/components/Chat.tsx](frontend/components/Chat.tsx): 챗봇 UI 렌더링
- [frontend/components/ChartRenderer.tsx](frontend/components/ChartRenderer.tsx): 차트/표 파싱 및 시각화

## 보안 운영 기준

이 서비스는 보안이 가장 중요한 운영 요소입니다. 운영 시 다음 기준을 지켜야 합니다.

1. [backend/mcp_server/views_whitelist.py](backend/mcp_server/views_whitelist.py)에 명시된 매출 뷰만 조회 가능하도록 유지한다.
2. [backend/mcp_server/sql_guard.py](backend/mcp_server/sql_guard.py)가 SQL 검증을 수행하도록 유지한다.
   - SELECT 단일 문장만 허용한다.
   - 다중 문장 실행을 차단한다.
   - INSERT, UPDATE, DELETE, DROP 등 DML/DDL과 위험 키워드를 차단한다.
   - FROM/JOIN 대상이 화이트리스트 뷰인지 확인한다.
   - TOP 절이 없으면 최대 1000행 제한을 자동 삽입한다.
3. DB 접속 계정은 해당 뷰에 대한 SELECT 권한만 가진 전용 계정으로 관리한다.
4. 사용자 입력을 직접 SQL 문자열에 결합하지 않도록 운영 절차를 유지한다.

## 운영 준비 사항

운영 환경에서는 다음 항목을 먼저 준비해야 합니다.

- Python 환경 및 Node.js 환경
- ODBC Driver 18 for SQL Server 설치
- [backend/.env](backend/.env) 또는 운영용 환경 변수에 GEMINI_API_KEY, MSSQL_* 값 설정
- 백엔드/프론트엔드 배포 경로와 프록시 구성 확인

## 실행 방법

### 1) 백엔드 실행

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

### 2) 프론트엔드 실행

```bash
cd frontend
npm install
npm run dev
```

브라우저에서 http://localhost:3000에 접속한다.

## 장애 대응 및 모니터링

운영 중에는 다음을 점검하는 것이 좋습니다.

- DB 연결 실패 시 서비스 응답이 정상적으로 반환되는지
- Gemini API 응답 지연 또는 실패 시 적절한 에러 메시지가 표시되는지
- MCP 서버 기동 실패 시 서비스가 안전하게 실패하는지
- 요청 ID, 에러 로그, 응답 시간 등을 기록해 원인을 파악할 수 있는지

## 점검 및 검증

개발 및 운영 점검 시 아래 경로의 스크립트나 테스트를 참고하면 됩니다.

- [backend/scripts/test_db_connection.py](backend/scripts/test_db_connection.py)
- [backend/scripts/test_mcp_client.py](backend/scripts/test_mcp_client.py)
- [backend/scripts/test_chat_err.py](backend/scripts/test_chat_err.py)
- [backend/tests](backend/tests)
- [frontend/components/__tests__](frontend/components/__tests__)

## 운영 권장 사항

- 민감한 값은 저장소에 직접 포함하지 않고 운영 환경의 환경 변수나 시크릿 매니저로 관리한다.
- 보안 규칙이나 화이트리스트 변경 시에는 영향 범위를 반드시 검토한다.
- 배포 후에는 서비스 응답, DB 조회, 에러 로그를 확인해 정상 운영 상태를 점검한다.
