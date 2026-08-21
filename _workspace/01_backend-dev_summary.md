# 01 backend-dev — 이메일 수신자 프리셋 (EMAIL_PRESET_RECIPIENTS)

## 프론트가 참고할 계약 (확정)

**엔드포인트:** `GET /api/report/email/presets`

**응답 (항상 200):**
```json
{ "presets": ["sales@company.com", "manager@company.com"] }
```

- `presets`: `string[]`. 이메일 주소 문자열 배열. 순서는 `.env`에 적힌 순서 그대로.
- 미설정 시 `{"presets": []}` (200). **503/404를 내지 않는다** — SMTP_HOST /
  ALLOWED_EMAIL_DOMAINS가 비어 이메일 기능이 비활성이어도 200 + 빈 리스트다.
  따라서 프론트는 마운트 시점에 조건 없이 호출해도 안전하다.
- `presets` 키는 항상 존재한다(응답 모델 `EmailPresetsResponse`가 보장).
- 인증/쿼리 파라미터 없음. 요청 본문 없음.

## 프리셋의 의미 (중요)
프리셋은 **추천 목록일 뿐**이다. 서버는 프리셋만 허용하도록 제한하지 않는다.
`POST /api/report/email`의 수신자 검증은 여전히 `ALLOWED_EMAIL_DOMAINS`(mailer.validate_recipients)가
전담한다. 즉:
- 프리셋에 없는 주소도 도메인만 맞으면 발송 가능하다 → 프론트는 자유 입력을 계속 허용해야 한다.
- 반대로 프리셋에 있어도 도메인 화이트리스트를 통과 못 하면 403이 날 수 있다.

## 변경 없음 (건드리지 않음)
- `POST /api/report/email` 및 `to: list[str]` 다중 수신자 계약 — 기존 그대로.
- `backend/app/mailer.py` — 변경 없음.

## 변경 파일
1. `d:\WebDev\AI_Agent\backend\app\config.py`
   - `EMAIL_PRESET_RECIPIENTS` 추가. `ALLOWED_EMAIL_DOMAINS`와 동일한 콤마 split + strip 스타일.
     원본 대소문자 표기는 보존(소문자 정규화는 mailer 책임). 빈 값 → `[]`.
2. `d:\WebDev\AI_Agent\backend\app\main.py`
   - `EmailPresetsResponse` 모델 + `GET /api/report/email/presets` 핸들러 추가.
     `config.EMAIL_PRESET_RECIPIENTS`를 요청 시점에 참조(테스트 monkeypatch 가능).
     MCP/SQL에 전혀 접근하지 않는 순수 설정 조회 엔드포인트.
3. `d:\WebDev\AI_Agent\backend\.env.example`
   - 이메일 섹션 하단에 `EMAIL_PRESET_RECIPIENTS`와 설명 주석 추가.
4. `d:\WebDev\AI_Agent\backend\tests\test_email_report.py`
   - 신규 테스트 4건: 설정값 반환 / 미설정 시 빈 리스트 / 이메일 비활성 상태에서도 200 /
     MCP 세션 미접근.

## 테스트 결과
- `pytest backend/tests/test_email_report.py backend/tests/test_pdf_report.py -q` → **41 passed**
- `pytest backend/tests -q` (전체) → **176 passed**, 회귀 없음.
