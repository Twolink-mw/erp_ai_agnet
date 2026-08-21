# 요청 스코프 분석 — 이메일 고정 수신자 콤보박스

## 요청
자주 쓰는 수신자 이메일 주소를 .env에 등록해두면, 프론트엔드 이메일 발송 UI에서
그 주소들이 콤보박스(드롭다운)로 나타나고 여러 개를 체크(멀티 선택)해서
한 번에 여러 수신자에게 보낼 수 있어야 한다.

## 기존 구현 확인 (이번 요청과의 차이)
- 백엔드 `/api/report/email`은 이미 `to: list[str]`을 받고 `mailer.validate_recipients()`가
  리스트 전체를 검증한다 — **다중 수신자 발송 자체는 이미 지원됨.**
- 프론트 `EmailSendButton`([frontend/components/Chat.tsx:165](frontend/components/Chat.tsx#L165))은
  현재 텍스트 입력창 1개로 `to: [to]` (단일 주소)만 보낸다 — 콤보박스/멀티선택 UI가 없음.
- 고정 수신자 프리셋을 .env에 등록하는 기능 자체가 없음 — `backend/app/config.py`에 신규 추가 필요.

## 건드리는 계층
- **app**: `backend/app/config.py`에 `EMAIL_PRESET_RECIPIENTS` 파싱 추가,
  `backend/app/main.py`에 프리셋 목록을 프론트에 노출하는 조회 엔드포인트 추가,
  `backend/.env.example`에 신규 변수 문서화.
- **frontend**: `EmailSendButton`을 프리셋 체크박스(멀티선택) + 직접입력 병행 UI로 확장,
  선택된 여러 주소를 `to` 배열로 전송.
- **mcp_server**: 변경 없음.

## 판단
2개 계층(app, frontend) → **Phase 2B 팀 경로**. mcp-guardian 불참.

## 의존 관계
1. backend-dev: `config.py`(EMAIL_PRESET_RECIPIENTS) + `main.py`(GET 프리셋 엔드포인트) +
   `.env.example` 문서화. 응답 스키마 확정 후 frontend-dev에게 SendMessage.
2. frontend-dev: 확정된 프리셋 엔드포인트 스키마를 받아 콤보박스(멀티체크) UI 구현,
   기존 텍스트 입력과 병행 가능하게, `to` 배열로 발송.
3. qa-verifier: 양쪽 완료 후 pytest + vitest 전체 실행, 프리셋 응답 스키마 ↔ 프론트 파싱 계약,
   기존 단일 발송 경로(하위호환) 검증.
