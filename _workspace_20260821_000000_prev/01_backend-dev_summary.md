# backend-dev 작업 요약 — 조회 결과 이메일 발송 (백엔드)

## 변경/신규 파일

- 신규: `backend/app/mailer.py` — SMTP 발송 순수 계층 (DB/MCP/SQL 미접근)
- 신규: `backend/tests/test_email_report.py` — mailer 단위 테스트 + `/api/report/email` 엔드포인트 테스트
- 수정: `backend/app/config.py` — SMTP_*/ALLOWED_EMAIL_DOMAINS 환경변수 추가, `SYSTEM_PROMPT`의 "PDF로 만들어줘" 문단을 이메일 요청 케이스까지 확장
- 수정: `backend/app/main.py` — `EmailReportRequest`, `POST /api/report/email` 엔드포인트 추가
- 수정: `backend/.env.example` — SMTP 관련 항목과 한글 주석 추가

`backend/app/pdf_report.py`는 이번 작업에서 변경하지 않았습니다 (기존 "순수 렌더링 계층" 그대로 재사용).

## `POST /api/report/email` 스펙

### 요청 (`EmailReportRequest` = `PdfReportRequest` 확장)

`PdfReportRequest`의 모든 필드(`title`, `question`, `content`, `tables`, `charts`, `generated_at`, `filename`)에 `to` 필드가 추가됩니다.

```jsonc
{
  "title": "매출 리포트",          // optional, 기본 "ERP 매출 분석 리포트"
  "question": "상반기 매출은?",     // optional
  "content": "# 제목\n\n...",       // 마크다운 (표/```chart 블록 포함 가능)
  "tables": [ /* ReportTable[] — pdf_report.py 참고 */ ],
  "charts": [ /* ReportChart[] — pdf_report.py 참고, ChartRenderer.tsx와 동일 스키마 */ ],
  "generated_at": "2026-08-20 10:00", // optional
  "filename": "report.pdf",         // optional, 첨부 파일명 힌트
  "to": ["user@company.com"]        // 필수, 사내 도메인 화이트리스트 통과해야 함
}
```

### 성공 응답 — `200`

```jsonc
{ "status": "sent", "to": ["user@company.com"] }
```

`to`는 검증/중복제거된 최종 수신자 목록입니다(요청에 중복이 있었으면 축소되어 반환됩니다).

### 에러 코드 매핑표

| 상태 코드 | 조건 | detail 예시 |
| --- | --- | --- |
| 503 | `SMTP_HOST` 또는 `ALLOWED_EMAIL_DOMAINS`가 미설정(빈 값) | "이메일 발송 기능이 설정되지 않았습니다." |
| 403 | 수신자 도메인이 화이트리스트 밖 | "허용되지 않은 이메일 도메인입니다: evil.com" |
| 422 | 수신자 목록이 비어 있음, 또는 이메일 형식 오류 | "수신자가 없습니다." / "올바르지 않은 이메일 형식입니다: ..." |
| 500 | PDF 생성 실패 (`build_pdf` 예외) — 내부 스택 미노출 | "PDF 생성에 실패했습니다." |
| 502 | SMTP 발송 실패 (`mailer.send_email`이 `EmailSendError`) — 내부 스택 미노출 | "이메일 발송에 실패했습니다." |

검증 순서: 503(설정 확인) → 403/422(수신자 검증) → 500(PDF 생성) → 502(발송). 즉 SMTP 미설정이면 수신자 형식이 잘못돼 있어도 항상 503이 먼저 반환됩니다.

## 프론트 참고 사항

- 수신자 이메일 주소는 챗봇(Gemini)이 절대 다루지 않습니다 — `SYSTEM_PROMPT`에 "수신자는 묻지 않는다"는 지시를 명시했습니다. 발송 UI가 수신자 입력을 받아 이 엔드포인트에 직접 전달해야 합니다.
- 이 엔드포인트는 `/api/report/pdf`와 동일하게 요청 본문에 담긴 데이터만 사용하며 새 SQL/MCP 접근을 하지 않습니다.
- 이메일 기능 가용 여부(버튼 노출 여부)를 프런트에서 미리 알고 싶다면 현재는 별도 "기능 활성화 여부" 엔드포인트가 없으므로, 503 응답을 받았을 때 버튼을 숨기거나 안내 메시지로 대체하는 방식을 권장합니다. 필요하면 `/api/health`류의 별도 설정 노출 엔드포인트 추가를 backend-dev에게 요청하세요.

## 환경변수 (`backend/.env.example`에 추가됨)

```
SMTP_HOST=smtp.company.com
SMTP_PORT=587
SMTP_USER=erp-bot@company.com
SMTP_PASSWORD=your-smtp-password
SMTP_FROM=erp-bot@company.com
SMTP_USE_TLS=true
ALLOWED_EMAIL_DOMAINS=company.com   # 콤마 구분, 서브도메인 자동 허용, 기본값은 빈 문자열(전부 거부)
```

## 보안 설계 요점

- `mailer.sanitize_header_value()`가 Subject/To 값의 CR/LF를 제거해 헤더 인젝션(예: `제목\r\nBcc: attacker@evil.com`)을 방지합니다.
- `mailer.validate_recipient(s)`는 형식 오류(`ValueError`)와 도메인 거부(`EmailDomainNotAllowedError`)를 구분해 던지며, 엔드포인트에서 각각 422/403으로 매핑됩니다.
- 화이트리스트는 대소문자 무시 + 서브도메인 허용(`company.com` 설정 시 `mail.company.com` 통과)이며 기본값은 빈 리스트라 아무것도 통과하지 못합니다(fail-closed).
- `send_email()`은 모든 예외를 `EmailSendError`로 감싸 `raise ... from exc` 패턴을 사용하므로 SMTP 자격증명이나 내부 스택이 API 응답에 노출되지 않습니다.
- `mailer.py`는 DB/MCP/SQL에 전혀 접근하지 않는 순수 발송 계층으로, `pdf_report.py`와 동일한 설계 원칙(모듈 상단 docstring에 명시)을 따릅니다.

## 테스트 실행 결과

```
cd backend && python -m pytest tests/ -q
172 passed in 5.97s
```

`test_sql_guard.py`, `test_pdf_report.py` 포함 전체 스위트가 회귀 없이 통과했습니다. 신규 `test_email_report.py`는 다음을 검증합니다:
- `validate_recipient`: 허용 도메인/서브도메인/대소문자 무시 통과, 비허용 도메인 거부, 형식 오류 거부
- `validate_recipients`: 빈 리스트 거부, 중복 제거, 부분 실패 시 전체 실패
- `sanitize_header_value`의 CRLF 제거
- `/api/report/email`: 200(성공, `send_email` 목킹), 403(도메인 거부), 422(빈 수신자/형식 오류), 503(SMTP 미설정), 502(발송 실패), 그리고 `test_pdf_report.py`의 "MCP를 건드리지 않는다" 패턴을 복제한 `run_chat` 미호출 검증
