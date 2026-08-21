# 요청 스코프 분석 — 이메일 발송 기능

## 요청
챗봇 조회 결과(PDF 리포트)를 사내 도메인 화이트리스트 기반 SMTP로 발송하는 기능 추가.

## 건드리는 계층
- **app** (`backend/app/mailer.py` 신규, `backend/app/config.py`, `backend/app/main.py`, `SYSTEM_PROMPT`)
- **frontend** (`frontend/components/Chat.tsx` — `EmailSendButton` 추가)
- **mcp_server**: 변경 없음. `views_whitelist.py`/`sql_guard.py`/`db.py` 미변경. 단, "이메일 엔드포인트가 MCP 세션을 열지 않는다"는 계약을 반드시 테스트로 고정해야 하므로 mcp-guardian은 팀에는 불참하되 qa-verifier가 이 계약을 검증한다.

## 판단
2개 계층(app, frontend) → **Phase 2B 팀 경로**. 팀 구성: backend-dev, frontend-dev, qa-verifier (mcp-guardian 제외).

## 의존 관계
1. backend-dev: `mailer.py` 신규 + `config.py`(SMTP_*, ALLOWED_EMAIL_DOMAINS) + `main.py`(`POST /api/report/email`) + `SYSTEM_PROMPT` 이메일 안내 문구
2. frontend-dev: backend-dev가 확정한 `/api/report/email` 요청/응답 스키마를 받아 `EmailSendButton` 구현 (backend-dev 완료 후 진행)
3. qa-verifier: 양쪽 완료 후 pytest(`test_email_report.py` 포함) + vitest 전체 실행, 경계면 정합성(`EmailReportRequest`↔프론트 fetch body, MCP 미접근 계약) 검증
