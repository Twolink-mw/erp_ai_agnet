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
- [backend/app/main.py](backend/app/main.py): FastAPI 엔드포인트, API 요청 처리
- [backend/app/gemini_agent.py](backend/app/gemini_agent.py): Gemini 함수 호출 루프, MCP 도구 실행 오케스트레이션
- [backend/app/mcp_client.py](backend/app/mcp_client.py): MCP 클라이언트 세션 생성/종료 관리
- [backend/app/config.py](backend/app/config.py): 시스템 프롬프트 및 에이전트 설정
- [backend/mcp_server/server.py](backend/mcp_server/server.py): MCP stdio 서버 진입점
- [backend/mcp_server/views_whitelist.py](backend/mcp_server/views_whitelist.py): 허용된 매출 뷰, 별칭 매핑, 쿼리 치환
- [backend/mcp_server/sql_guard.py](backend/mcp_server/sql_guard.py): SQL 검증, 읽기 전용 제한, 금지 패턴 검사
- [backend/mcp_server/db.py](backend/mcp_server/db.py): DB 연결 및 권한 전제
- [frontend/components/Chat.tsx](frontend/components/Chat.tsx): 챗봇 UI 렌더링
- [frontend/components/ChartRenderer.tsx](frontend/components/ChartRenderer.tsx): 차트/표 파싱 및 렌더링

## 구현 시 반드시 지켜야 할 규칙
- 새 매출 뷰는 반드시 화이트리스트에 등록해야 한다.
- SQL은 SELECT만 허용해야 한다.
- INSERT, UPDATE, DELETE, DDL은 금지된다.
- 사용자 입력을 직접 SQL 문자열에 결합하지 않는다.
- 보안 가드나 화이트리스트를 변경할 때는 전체 보안 흐름을 함께 검토한다.
- MCP 세션은 요청마다 새로 열고 닫는 구조를 유지한다.
- 차트 결과는 프론트엔드가 파싱 가능한 형식으로 반환해야 한다.

## 개발 체크리스트
- 변경이 백엔드, 프론트엔드, 또는 보안 가드 중 어디에 영향을 주는지 확인한다.
- 기존 API/도구 스펙과 프론트엔드 파싱 계약이 깨지지 않는지 검토한다.
- 관련 테스트 또는 점검 스크립트를 실행한다.
- 보안 위반 가능성이 없는지 최종 확인한다.

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
copy .env.example .env
cd ..
uvicorn backend.app.main:app --reload --port 8000
```
> **주의:** 마지막 `uvicorn` 실행은 반드시 워크스페이스 루트([d:\WebDev\AI_Agent](d:\WebDev\AI_Agent))에서 해야 한다.
> [backend/app/mcp_client.py](backend/app/mcp_client.py)가 MCP 서버를 `python -m backend.mcp_server.server`로 서브프로세스 실행하는데,
> `backend/` 안에서 uvicorn을 띄우면(cwd가 `backend/`가 되면) `backend` 패키지를 찾지 못해
> `ModuleNotFoundError: No module named 'backend'`로 MCP 연결이 실패하고 챗봇에 "도구 연결 실패" 메시지가 뜬다.

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

