# QA 리포트 — 조회 결과 이메일 발송 기능

검증 대상: `backend/app/mailer.py`(신규), `backend/app/config.py`, `backend/app/main.py`,
`backend/.env.example`, `backend/tests/test_email_report.py`, `frontend/components/Chat.tsx`(EmailSendButton),
`frontend/components/__tests__/Chat.test.tsx`

## 테스트 스위트

- pytest: **172/172 통과** (`cd backend && python -m pytest tests/ -q`, 5.14s). `test_sql_guard.py`, `test_pdf_report.py`, `test_email_report.py` 전부 포함, 회귀 없음.
- vitest: **39/39 통과** (`cd frontend && npx vitest run`, `ChartRenderer.test.tsx` 15개 + `Chat.test.tsx` 24개). 회귀 없음.
  - 참고(문제 아님): `Chat.test.tsx > shows an error message when the fetch call rejects`에서 `act(...)` 경고가 stderr에 출력됨. frontend-dev 요약에서도 명시했듯 이번 변경과 무관한 기존 테스트에서 나는 경고이며 테스트는 통과함. 수정 불필요.

## 우선 확인 요청 사항 — 요청 바디 필드 불일치 여부 판정

**결론: 실제 불일치 아님. frontend-dev의 판단이 맞다.**

- `backend/app/pdf_report.py:68-76`의 `PdfReportRequest`: `content`만 기본값 `""`이고 `title`/`question`/`tables`/`charts`/`generated_at`/`filename` 전부 `None` 또는 `default_factory=list`로 optional. `backend/app/main.py:96-97`의 `EmailReportRequest(PdfReportRequest)`는 여기에 `to: list[str] = Field(default_factory=list)`만 추가하므로, `{content, question, to}`만 보내도 422 없이 정상 파싱된다(`to`가 비어 있으면 이후 `validate_recipients`에서 422로 거부되지만 이는 스키마 검증이 아니라 비즈니스 검증).
- `pdf_report.py:479` `build_pdf()`는 `parse_markdown_blocks(req.content)`로 `content` 안의 마크다운 표(`table` 블록, `:135-231`의 `_TABLE_SEP_RE` 기반 파서)와 ` ```chart ` 펜스(`:174-183`, `ReportChart.model_validate(json.loads(raw))`)를 전부 인라인으로 파싱해 표/차트를 렌더링한다. `req.tables`/`req.charts`(:507-515)는 이 인라인 파싱과 **별개로 추가되는** 필드이지 필수 경로가 아니다. 즉 `content`만 보내도 표/차트가 빠지지 않는다.
- `test_pdf_report.py`가 이미 이 패턴(콘텐츠 인라인 표/차트만으로 렌더링)을 검증하고 있고, `test_email_report.py:15`의 `SAMPLE_CONTENT`도 인라인 마크다운 표만 포함해 `test_report_email_endpoint_success`(:89-101)가 `{title, content, to}`만으로 200을 확인함 — 새로운 경계면 위험 없이 기존에 이미 검증된 패턴의 재사용이다.
- 지시서 원안(`title`/`tables`/`charts`/`generated_at`/`filename` 포함 예시)과의 차이는 실제 컴포넌트 계약(`PdfDownloadButton`이 이미 `{content, question}`만 보냄, `tables`/`charts`는 "중복 렌더링 유발"로 의도적 제외)을 우선한 정당한 선택이며, 코드 수정 불필요.

## 경계면 검증

- [통과] MCP 미접근 계약: `main.py`의 `report_email()`(:100-144) 전체를 읽음. import 그래프상 `mailer`, `pdf_report`, `config`만 사용하고 `run_chat`을 호출하지 않는다. `test_email_report.py:147-158`의 `test_report_email_endpoint_does_not_touch_mcp`가 `main.run_chat`을 호출 시 `AssertionError`를 던지도록 몽키패치해 200이 나오는지까지 직접 확인 — 코드 레벨/테스트 레벨 이중 확인 완료.
- [통과] 프론트-백엔드 정합성: `EmailSendButton`(`frontend/components/Chat.tsx:183-187`)이 보내는 `{content, question: question ?? null, to: [to]}`가 `EmailReportRequest`(`main.py:96-97`, `pdf_report.py:69-75`)의 필드명과 정확히 일치. 에러 처리(`Chat.tsx:189-196`)는 `res.json()?.detail`을 우선 사용하고 파싱 실패 시 기본 문구로 폴백 — `HTTPException(detail=...)`(`main.py:108,113,115,121,142`) 응답 형식과 일치.
- [통과] CLAUDE.md 보안 원칙 준수: `git diff HEAD --stat`로 이번 이메일 기능이 건드린 파일은 `config.py`/`main.py`/`Chat.tsx`(및 신규 `mailer.py`, `test_email_report.py`)뿐이며, `views_whitelist.py`/`sql_guard.py`/`db.py`는 이번 세션 시작 이전부터 이미 작업 트리에 존재하던 별개의 미커밋 변경(초기 `git status` 스냅샷에서도 이미 `M` 상태)으로, 이번 이메일 기능 작업과는 무관함을 확인. 이메일 기능 자체는 세 보안 파일을 전혀 건드리지 않았다.

## 보안 검토

- [통과] `validate_recipient`(`mailer.py:47-60`)는 fail-closed: `ALLOWED_EMAIL_DOMAINS` 기본값이 `[]`(`config.py:23-27`, `if d.strip()`로 빈 문자열 필터링되어 빈 리스트 유지)이므로 `_domain_allowed`(:39-44)가 항상 `False`를 반환해 전부 거부됨. 대소문자 무시(`domain.lower()`)와 서브도메인 허용(`domain.endswith("." + allowed)`)이 화이트리스트 확장 방향으로만 동작하고 우회 방향(예: `evil-company.com`이 `company.com`으로 오인되는 것)은 `endswith("." + allowed)` 조건이 정확히 점(`.`)을 포함해 검사하므로 발생하지 않음을 코드로 확인 (`evilcompany.com`.endswith(".company.com") == False).
- [통과] `sanitize_header_value`(`mailer.py:34-36`)가 정규식 `_CRLF_RE = re.compile(r"[\r\n]+")`로 CR/LF를 공백으로 치환. `test_email_report.py:78-83`에서 `"제목\r\nBcc: attacker@evil.com"` 입력 시 개행이 전부 제거되고 텍스트("Bcc:")는 남되 헤더 분리가 불가능해짐을 직접 확인. 추가로 `To` 헤더(`mailer.py:92`)에 들어가는 값도 `validate_recipient`의 정규식(`_EMAIL_RE`, 공백/개행 불허)을 통과한 주소만 들어가므로 이중 방어 구조.
- [통과] SMTP 자격증명/스택 미노출: `send_email()`(`mailer.py:103-114`)이 모든 예외를 `EmailSendError("이메일 발송에 실패했습니다.") from exc`로 감싸고, `main.py:139-142`도 `str(exc)`(즉 고정 문구)만 502 `detail`로 노출. PDF 생성 실패도 `main.py:117-121`에서 `except Exception: raise HTTPException(..., detail="PDF 생성에 실패했습니다.")`로 스택 미노출. 코드 레벨로 확인됨.

## 발견된 문제

없음. 회귀, 보안 이슈, 경계면 불일치 전부 미발견.

## 최종 판정

**통과.** 백엔드/프론트엔드 모두 추가 수정 불필요.
