# Scope 판단

## 요청
챗봇 답변(매출 조회 결과)을 PDF 리포트로 생성/다운로드하는 기능 추가.

## 판단
- app 계층: 백엔드에 PDF 생성 엔드포인트 필요 (FastAPI), Gemini 에이전트가 "PDF로 만들어줘" 요청을 인식하도록 시스템 프롬프트/도구 조정 필요
- frontend 계층: Chat.tsx/ChartRenderer.tsx에 다운로드 버튼 노출 필요
- mcp_server 계층: 해당 없음 (SQL 화이트리스트/가드 변경 없음, 사용자가 명시적으로 이 범위 제외 요청)

→ 2개 계층(app, frontend) 해당 → Phase 2B (다중 계층, 에이전트 팀 경로)
팀 구성: backend-dev + frontend-dev + qa-verifier (mcp-guardian 불참)
