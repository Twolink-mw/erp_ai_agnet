# QA 리포트 — 이메일 프리셋 수신자 콤보박스

결론: **통과** (차단성 문제 없음. 관찰 사항 2건은 참고용 nit)

## 테스트 스위트
- pytest (`backend/tests`, 루트 pytest.ini, asyncio_mode=auto): **176/176 통과** (5.36s, 실패 0)
- vitest (`frontend`, `npx vitest run`): **48/48 통과** (2 파일, 5.23s, 실패 0)
  - Chat.test.tsx 33건 / ChartRenderer.test.tsx 15건
  - stderr에 기존 `act(...)` 경고 2건 — "fetch reject" 테스트에서 발생하는 기존 노이즈이며 실패 아님

## 경계면 검증

### [통과] GET /api/report/email/presets 응답 스키마 ↔ 프론트 파싱
- 백엔드: `backend/app/main.py:100-113` — `EmailPresetsResponse(presets: list[str])`, `response_model`로 고정되어 추가 키가 새지 않음
- 프론트: `frontend/components/Chat.tsx:208-215` — `Array.isArray(data?.presets)` 확인 후 문자열/비어있지 않음으로 필터, 아니면 `[]` 폴백
- 실측: `{'presets': ['sales@company.com', 'manager@company.com']}` — 키 이름·타입 일치

### [통과] 이메일 기능 비활성 상태에서 presets 200 + 프론트 폴백
- `backend/tests/test_email_report.py:166-173`(SMTP_HOST/ALLOWED_EMAIL_DOMAINS를 monkeypatch로 비움) 통과 — 503이 아닌 200 반환 확인
- 빈 목록: `test_email_presets_returns_empty_list_when_unset` 통과, 프론트는 `Chat.tsx:305`의 `presets.length > 0` 가드로 드롭다운 자체를 렌더링하지 않고 텍스트 입력만 남김 (`Chat.test.tsx:488` 하위호환 케이스로 커버)
- 네트워크 실패: `Chat.tsx:216-218` catch에서 조용히 무시 → 직접 입력으로 계속 진행 (`Chat.test.tsx:618` reject 케이스로 커버)
- 비-200 응답(구버전 백엔드 404 등): `Chat.tsx:209`의 `if (!res?.ok) return`으로 폴백 — 코드상 안전(전용 테스트는 없음)

### [통과] POST /api/report/email `to: list[str]` 계약 ↔ 병합 결과, 이중 방어
- 프론트 `mergeRecipients` (`Chat.tsx:165-180`): 프리셋 선택 + 직접입력(`,`/`;` 분리)을 합쳐 **소문자 키 기준 중복 제거**, 원본 표기 유지 → 배열 그대로 `to`로 전송 (`Chat.tsx:246`)
- 서버 `mailer.validate_recipients` (`backend/app/mailer.py:63-76`): **동일하게 strip+lower 기준 중복 제거 후** 각 주소를 형식 검증 + 도메인 화이트리스트 검증. 하나라도 실패하면 전체 실패
- 실측(프론트를 신뢰하지 않고 서버만 호출):
  - `['Sales@Company.com','sales@company.com']` → `['Sales@Company.com']` (서버 단독 dedupe 동작)
  - `['bad-addr']` → ValueError(422 매핑)
  - `['evil@outside.com']` → EmailDomainNotAllowedError(403 매핑)
  - `[]` → ValueError("수신자가 없습니다", 422)
- 즉 **프론트 dedupe가 전부 빠져도 서버가 단독으로 안전**하며, 그 반대도 성립. 한쪽만 믿는 구조 아님
- 프리셋 우회 여부: 프리셋 목록은 "추천"일 뿐 발송 허용 목록이 아니며(`main.py:110-111` 주석과 실제 코드 일치), 프리셋에 들어있는 외부 도메인 주소도 발송 단계에서 403으로 차단됨을 실측 확인

### [통과] "이메일 엔드포인트는 MCP 세션을 열지 않는다" 계약 유지
- `main.py:104-113`의 presets 핸들러는 `config.EMAIL_PRESET_RECIPIENTS`만 읽는다 — `run_chat`/`gemini_agent`/`mcp_client` 참조 없음
- `main.py:116-160`의 send 핸들러도 `mailer` + `pdf_report`만 사용
- 회귀 테스트로 고정됨: `test_email_report.py:176`(presets), `:184`(send) — `main.run_chat`을 예외 발생 함수로 monkeypatch한 상태에서 각각 200

### [통과] 기존 테스트의 `/api/report/email` includes 매칭 충돌 수정
- fetch 모킹(`Chat.test.tsx:319-322`)이 `/api/report/email/presets`를 **먼저** 검사한 뒤 `/api/report/email`을 검사 — 순서가 올바름
- 단언부는 전부 `includes`가 아닌 **완전 일치**로 전환됨: `:382`, `:472`(`String(c[0]) === "/api/report/email"`), `:571`(`some(... === ...)`), `:517/:535/:557`은 `toHaveBeenCalledWith("/api/report/email", expect.anything())`로 인자 개수까지 달라 GET presets(1-인자 호출)와 매칭되지 않음
- 따라서 "presets GET이 send POST로 오인되는" 문제는 실제로 해소됨. `:562` "발송 안 함" 케이스가 특히 이 수정에 의존하는데 통과 확인

### [미검증 — 이번 변경 범위 밖]
- 화이트리스트 ↔ SQL 가드, MCP 도구 ↔ Gemini FunctionDeclaration, chart 스키마, MCP 환경변수 전달: 이번 diff가 `mcp_server/`·`gemini_agent.py`의 해당 로직을 건드리지 않아 별도 재검증 생략(pytest 176건에 기존 가드 테스트 포함, 전량 통과)
- `backend/scripts/test_db_connection.py` 등 수동 점검 스크립트: 실제 DB/Gemini 연결이 필요해 미실행(`.env`는 존재하나 사용자 승인 없이 실행하지 않음)

## 관찰 사항 (차단성 아님)
1. `backend/app/config.py:31-35` — `EMAIL_PRESET_RECIPIENTS` 파싱이 중복 제거를 하지 않는다. `.env`에 동일 주소가 두 번 들어가면 `Chat.tsx:351-353`의 `presets.map(... key={addr})`에서 React 중복 key 경고가 난다. 발송 결과는 프론트/서버 dedupe로 안전. 수정하려면 config.py에서 소문자 키 기준 dedupe를 추가하면 된다.
2. `frontend/components/Chat.tsx:166-169` — 직접 입력 분리자가 `,`와 `;`뿐이라 공백/개행으로 구분해 붙여넣은 주소는 하나의 잘못된 주소로 서버에 전달되어 422가 된다. 서버가 안전하게 거부하므로 보안 문제는 없고 UX nit. 필요하면 `/[,;\s]+/`로 확장 가능.
