# 03 · qa-verifier — PDF 리포트 기능 검증

## 요약

| 항목 | 결과 |
| --- | --- |
| pytest (`backend/tests`) | **117 passed** |
| vitest (`frontend`) | **32 passed** (2 files) |
| `npx tsc --noEmit` | 실패 → **수정 완료**, 통과 |
| `npx next build` | 실패 → **수정 완료**, `✓ Compiled successfully` |
| `/api/report/pdf` 라이브 요청 | **200 + application/pdf** |
| 경계면 정합성 (4종) | 전부 통과 |
| 신규 발견 | 선행 SQL 가드 우회 1건 (PDF 기능과 무관, **미수정**) |

---

## 1. 테스트 스위트

```
pytest              117 passed in 4.61s
vitest              Test Files 2 passed / Tests 32 passed (32)
```
둘 다 실패 0건. 사전 보고된 수치(117 / 32)와 일치. 회귀 없음.

`backend/scripts/test_db_connection.py` 등 수동 점검 스크립트는 실제 DB/Gemini 연결이 필요하므로 실행하지 않았다.

## 2. 경계면 정합성

### [통과] `ChatResponse.report_available` ↔ 프론트 `Message.reportAvailable`
- `backend/app/main.py:52` `report_available: bool = False`
- `frontend/components/Chat.tsx:13` `reportAvailable?: boolean`, `:192` `data?.report_available ?? false`
- snake_case → camelCase 변환 지점이 `send()` 한 곳뿐이고 `?? false` 방어가 있어, 필드 없는 구버전 응답에서도 버튼이 뜨지 않는다. 이름/타입 일치.
- `main.py:58`의 `result.setdefault(...)`로 `run_chat()`이 이 키를 내지 않아도 서버에서 채워진다.

### [통과] `/api/report/pdf` 요청 스키마 ↔ 프론트 전송 필드
- 백엔드 `PdfReportRequest`(`pdf_report.py:68-75`): `title`/`question`/`content`/`tables`/`charts`/`generated_at`/`filename` — `content`를 뺀 전부가 옵셔널이고 `content`도 기본 `""`.
- 프론트 `Chat.tsx:100`: `{ content, question: question ?? null }`만 전송.
- `question`은 `str | None`이라 `null` 허용. 나머지 필드는 기본값이 있어 422가 발생하지 않는다. 라이브 요청으로 실증 확인.
- `Content-Disposition` 파싱도 일치: 백엔드가 `filename="ascii"; filename*=UTF-8''<pct>` 순으로 내고(`main.py:77-80`), 프론트 `filenameFromDisposition()`(`Chat.tsx:66-`)이 `filename*` 우선 → `filename` → 기본값 순으로 읽는다. CORS `expose_headers=["Content-Disposition"]`(`main.py:34`)도 있음.

### [통과] PDF 경로가 SQL/MCP를 건드리지 않음
- `backend/app/pdf_report.py`의 import는 stdlib + pydantic + reportlab뿐. `db`/`mcp_client`/`views_whitelist`/`sql_guard` 참조 0건.
- `main.py:62-89`의 `report_pdf()`도 `build_pdf(req)`만 호출. 데이터는 100% 요청 본문 출처.
- `mcp_server/` 전체가 이번 변경에서 미수정(git status로 확인).
- 회귀 방지 테스트 `test_report_pdf_endpoint_does_not_touch_mcp` 존재.

### [통과] chart 스키마 3자 정합 (프롬프트 ↔ ChartRenderer ↔ PDF)
| 위치 | 필드 |
| --- | --- |
| `config.py:26-28` SYSTEM_PROMPT | `type`, `title`, `xKey`, `series[{key,name}]`, `data` |
| `ChartRenderer.tsx:19-24` `ChartSpec` | 동일 |
| `pdf_report.py:58-65` `ReportChart` | 동일 |

세 곳 필드명·구조가 완전히 일치. PDF 쪽이 `type` 기본값 `"bar"`를 갖는 반면 프론트는 `bar|line`을 엄격히 요구하는 비대칭이 있으나, PDF가 더 관대한 방향이라 렌더 실패로 이어지지 않는다.

### [통과] MCP 도구 ↔ Gemini FunctionDeclaration
- `server.py`가 노출하는 5개: `list_sales_views`, `get_view_schema`, `get_view_aliases`, `get_column_aliases`, `run_sql`.
- `gemini_agent.py:39-49`는 `list_tools()` 결과를 순회해 동적으로 변환(하드코딩 없음) → 1:1 자동 일치. 도구 추가 시 누락 위험 없음.

### [통과] 환경변수 전달
- `mcp_client.py:35` `env=dict(os.environ)` — MCP SDK 기본 OS 화이트리스트 대신 전체 환경을 명시 전달하므로 `MSSQL_*`/`GEMINI_*` 누락 없음.

## 3. 인계된 선행 이슈 — 수정 완료

**`frontend/vitest.setup.ts:12`**

```
vitest.setup.ts(12,1): error TS2578: Unused '@ts-expect-error' directive.
```

- **PDF 기능과 무관한 기존 이슈임을 확인**: git status상 `vitest.setup.ts`는 이번 변경에서 수정되지 않은 커밋 상태 파일이며, 변경분은 `Chat.tsx` / `Chat.test.tsx` 두 개뿐이다.
- 원인: `global.ResizeObserver = ResizeObserverPolyfill` 대입이 현재 타입 설정에서 이미 정상 통과하므로 억제 지시자가 불필요해졌고, `@ts-expect-error`는 "억제할 에러가 없으면" 그 자체가 에러가 된다.
- **수정**: 지시자 한 줄을 일반 주석으로 교체(코드 동작 무변경).
- **재검증**: `npx tsc --noEmit` 통과, `npx next build` 통과, vitest 32개 재실행 통과.

## 4. 통합 확인 — 워크스페이스 루트 기동

포트 8000에 PDF 엔드포인트가 없는 구버전 uvicorn(PID 28284)이 남아 있어 종료 후, 루트에서 재기동:

```
d:\WebDev\AI_Agent> backend\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --port 8000
```

- `/api/health` → `{"status":"ok"}`
- `/openapi.json` paths → `/api/chat`, `/api/report/pdf`, `/api/health` (신규 엔드포인트 노출 확인)
- 마크다운 표 + ```chart 블록이 든 `{content, question}` POST 결과:

```
status: 200
content-type: application/pdf
content-disposition: attachment; filename="sales_report_....pdf"; filename*=UTF-8''sales_report_....pdf
content-length: 4513 (실제 바이트와 일치)
magic: %PDF-1.4,  %%EOF 트레일러 정상
```

MCP 서브프로세스 실행 인자는 `-m backend.mcp_server.server`(`mcp_client.py:31`)이므로 루트 기동이 전제다. 이 프로세스는 검증 후에도 8000에 띄워둔 상태이며, 브라우저 골든 패스(localhost:3000) 확인이 가능하다.

## 5. 신규 발견 — SQL 가드 우회 (PDF 기능과 무관 / 선행 이슈 / **미수정**)

**`backend/mcp_server/sql_guard.py:22-24`**

```python
_TABLE_REF_PATTERN = re.compile(
    r"\b(?:FROM|JOIN)\s+\[?([A-Za-z0-9_]+)\]?\.\[?([A-Za-z0-9_]+)\]?", re.IGNORECASE
)
```

이 정규식은 **스키마 수식된**(`schema.name`) 참조만 매칭한다. `FROM SecretTable`처럼 한 부분짜리 이름은 아예 캡처되지 않아 화이트리스트 검사(`:51-57`)를 통과조차 하지 않고 지나간다. 단독으로 쓰이면 `referenced`가 비어 `:49`에서 막히지만, **화이트리스트 뷰가 하나라도 같이 참조되면 검사가 성립해버려 비수식 테이블이 그대로 통과한다.**

재현 (`validate_and_prepare()` 직접 호출, 전부 ALLOWED):

```
SELECT * FROM dbo.JINJU_SALES UNION SELECT * FROM SecretTable
SELECT * FROM dbo.JINJU_SALES a JOIN SecretTable b ON 1=1
SELECT * FROM dbo.JINJU_SALES WHERE 1 IN (SELECT 1 FROM SecretTable)
```

대조군 — 수식된 형태는 정상 차단:
```
SELECT * FROM dbo.JINJU_SALES UNION ALL SELECT a FROM sys.tables  → BLOCKED
```

MSSQL은 비수식 이름을 기본 스키마(보통 `dbo`)로 해석하므로 실제로 `dbo.SecretTable`에 도달한다. 나머지 우회 시나리오(다중 문장, 비화이트리스트 수식 뷰, CTE, 대소문자/공백 변형)는 모두 정상 차단됨을 확인했다.

- **완화 요인**: 3단째 방어인 DB 계정 권한(`db.py:3-4`). 다만 이는 코드가 강제하지 않는 *전제*이며, 계정이 읽을 수 있는 모든 객체가 노출 범위가 된다.
- **테스트 공백**: `backend/tests/test_sql_guard.py:110`이 수식된 `JOIN dbo.Employee`는 커버하지만 비수식 변형은 커버하지 않는다.
- **수정 제안** (가드 변경은 defense-in-depth 전체 검토가 필요하므로 mcp-guardian 소관으로 남김):
  1. `_TABLE_REF_PATTERN`을 스키마 부분 옵셔널(`(?:(\w+)\.)?(\w+)`)로 넓히고, 스키마 누락 시 기본 스키마를 보충해 화이트리스트와 대조. 단 CTE 이름·테이블 별칭 오탐 처리 필요.
  2. 또는 `FROM|JOIN` 뒤 토큰이 반드시 `schema.name` 형태가 아니면 거부하는 화이트리스트-온리 정책(더 단순하고 안전).
  3. 위 3개 재현 케이스를 `test_sql_guard.py`에 회귀 테스트로 고정.

## 6. 담당 에이전트 통보

backend-dev / frontend-dev 산출물에서는 **수정을 요할 불일치가 발견되지 않아 SendMessage를 보내지 않았다.** 5번 항목은 `mcp_server/` 소관이며 이번 변경 이전부터 존재한 선행 이슈다.

## 7. 남은 이슈

1. **[높음]** `sql_guard.py:22-24` 비수식 테이블 참조 우회 — mcp-guardian 처리 필요.
2. **[낮음]** 브라우저(localhost:3000)에서의 사용자 클릭 골든 패스는 미확인. 백엔드 8000은 정상 기동해 두었으므로 수동 확인 가능.
