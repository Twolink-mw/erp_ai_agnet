# 07 qa-verifier — 도구 호출 라운드 상한 상향 검증 리포트

검증 대상: `backend/app/config.py`(SYSTEM_PROMPT MSSQL 방언 지시), `backend/app/gemini_agent.py`(`MAX_TOOL_ROUNDS` 6→10)
검증자: qa-verifier / 독립 재현 기준 (backend-dev의 06 요약을 신뢰하지 않고 전부 재실행)

## 결론

**5개 검증 항목 전부 통과.** 회귀 없음. 변경을 그대로 유지해도 된다.
다만 이번 실기동에서 **선행 데이터 이슈(`SALES_DT` 컬럼 형식)** 가 라운드 예산을 크게 잠식하는 것을 관측했다 —
이번 변경의 결함은 아니지만, 상향된 여유(10)를 이미 9까지 소진시키는 요인이므로 별도 항목으로 기록한다(§6).

---

## 1. 테스트 스위트

| 스위트 | 결과 | 비고 |
|---|---|---|
| pytest | **144 passed** in 4.38s | `backend\.venv\Scripts\python.exe -m pytest backend/tests -q`, 실패 0 |
| vitest | **32 passed** (2 files) in 3.82s | `frontend> npm run test`, 실패 0 |

- pytest 144개는 06 요약의 수치와 일치. 독립 재실행으로 확인.
- vitest는 프론트 무수정이나 회귀 확인 차원에서 재실행 — `ChartRenderer.test.tsx` 15개, `Chat.test.tsx` 17개 전부 통과.
- vitest stderr에 `act(...)` 경고 2건이 출력되나 이는 기존부터 존재하던 경고이며 실패가 아니다(에러 경로 테스트의 비동기 상태 갱신).

## 2. 라운드 상한 10 ↔ `proxyTimeout` 120초 안전 여유 (재확인)

**통과.** 단, 06 요약의 "라운드당 3~8초" 가정 중 **실측은 상단에 가깝다**.

실측 근거 — 실기동 1(§3)에서 **라운드 10회를 전부 소진**하는 케이스가 실제로 발생했다:

- 도구 호출 9회 + 최종 텍스트 라운드 1회 = **라운드 10/10 소진**
- 총 소요 **64.7초** → 라운드당 평균 **약 6.5초**
- `next.config.js:7`의 `proxyTimeout: 120_000` 대비 **약 54% 여유** (55초 남음)

최악 가정(라운드당 8초)에서도 10라운드 = 80초로 120초 이내이며, 폴백 메시지를 프록시 타임아웃 이전에 반환할 수 있다.
06 요약의 "12 이상은 채택 불가" 판단도 실측과 정합한다(12×8초 = 96초로 여유가 24초까지 줄어들고, 실측 평균 6.5초 기준으로도 78초 → 마진 붕괴 직전).

- 백엔드 측에는 별도의 요청 타임아웃이 없다(`main.py:55` `chat` 엔드포인트, `gemini_agent.py:91` 루프). 유일한 상한이 라운드 수이므로, **`MAX_TOOL_ROUNDS`를 올릴 때는 반드시 이 계산을 다시 해야 한다**는 점을 상수 주석(`gemini_agent.py:13-16`)이 이미 명시하고 있어 적절하다.
- `sql_guard.py:220-221`의 `SELECT TOP 1000` 자동 삽입이 라운드당 SQL 실행 시간을 상수 상한으로 묶어주므로, 단일 라운드가 폭주해 120초를 혼자 잡아먹는 시나리오는 방어된다.

## 3. 실기동 재현 (독립 2건, 프론트 프록시 `localhost:3000` 경유)

프록시 경유로 보낸 이유: `proxyTimeout` 경로까지 함께 검증하기 위함.
기동 프로세스가 변경 코드를 반영 중임을 먼저 확인 — uvicorn 시작 15:19:06 > `config.py` 15:15:51 / `gemini_agent.py` 15:15:59.

### 실기동 1 — "지점별 매출 상위 3곳 + 그 3곳의 월별 추이 (차트 포함)"

- HTTP 200, **64.7초**, 도구 호출 **9회**(라운드 10/10 소진), 폴백 메시지 **미발생**
- **`LIMIT` 생성 0건** — 첫 조회부터 `SELECT TOP 3 CUST_NM, SUM(SALES_AMT) ... ORDER BY TotalSales DESC` 사용
- 기존 상한 6이었다면 이 질문은 **폴백 메시지에 걸렸을 것** → 상향의 실효성이 실측으로 확인됨
- 답변은 상위 3곳 매출은 정상 반환했으나 월별 추이는 실패(§6 원인)

### 실기동 2 — "최근 월별 매출 추이 + 매출 상위 5개 거래처 (차트 포함)"

- HTTP 200, **14.2초**, 도구 호출 **5회**(상한 10에 충분한 여유), 정상 답변
- **`LIMIT` 생성 0건** — `SELECT TOP 5 CUST_NM, SUM(SALES_AMT) ... ORDER BY total_sales_amount DESC`를 **1차 시도에 바로** 사용
- 도구 호출 순서: `list_sales_views` → `get_view_schema` → `get_column_aliases` → `run_sql`(월별 집계) → `run_sql`(TOP 5)
- 응답에 마크다운 표 2개 + ` ```chart ` 블록 포함, 블록 내용:
  `{"type":"line","title":"월별 매출 추이","xKey":"sales_month","series":[{"key":"total_sales_amount","name":"매출액"}],"data":[...]}`
  → `ChartRenderer.tsx:49-57`의 `parseChartSpec` 검증 조건(`type`∈{bar,line}, `xKey` string, `series` array, `data` array)을 전부 충족.

**LIMIT→TOP 프롬프트 지시는 2건 모두에서 실효 확인.** 재시도 왕복 0건.

## 4. 경계면 정합성 (스모크 재확인)

- **[통과] 화이트리스트 ↔ SQL 가드**: `validate_and_prepare()`에 우회 시나리오를 직접 투입해 전부 차단 확인.
  - `... ; DROP TABLE x` → 다중 문장 차단
  - `SELECT * FROM [dbo].[SECRET_TABLE]` → 화이트리스트 미등록 차단
  - `... WHERE 1=1; EXEC sp_executesql N'...'` → 다중 문장 차단
  - `WITH cte AS (SELECT * FROM SecretTable) SELECT * FROM cte` → SELECT 시작 아님 차단
  - `SELECT * FROM dbo.JINJU_SALES, SecretTable` (콤마 목록 우회) → `dbo.SecretTable` 차단
  - `SELECT * INTO NewT FROM ...` → 금지 키워드 차단
  - `SELECT * FROM srv.db.dbo.JINJU_SALES` → 3부분 이상 참조 차단
  - 정상 경로: `SELECT * FROM 매출`, `SELECT TOP 5 매출일, 매출액 FROM 매출` → 별칭 치환 후 `dbo.JINJU_SALES` / `SALES_DT, SALES_AMT`로 정상 재작성. 별칭 치환 → 키워드 검사 → 테이블 참조 검사 순서(`sql_guard.py:210-221`) 유지됨.
- **[통과] MCP 도구 ↔ Gemini FunctionDeclaration**: `server.py`의 5개(`list_sales_views:35`, `get_view_schema:40`, `get_view_aliases:54`, `get_column_aliases:59`, `run_sql:73`)를 `gemini_agent.py:43-53`이 `list_tools()` 결과로부터 **동적 변환**. 하드코딩 없음 → 도구 추가 시 자동 반영. 실기동에서 4종 실제 호출 확인.
- **[통과] chart 스키마 (백엔드 ↔ 프론트)**: `config.py:29-33`의 지시 스키마와 `ChartRenderer.tsx:19-24`의 `ChartSpec` 타입이 필드명·타입 모두 일치. 이번 SYSTEM_PROMPT 편집은 chart 블록 지시를 건드리지 않았음을 확인(변경분은 20~22행 MSSQL 항목 추가뿐). 실기동 2의 실제 출력으로 end-to-end 확인.
- **[통과] 환경변수 전달**: `mcp_client.py:35` `env=dict(os.environ)`로 전체 상속 유지. MCP 기본 OS 화이트리스트 문제 회피 상태 그대로. 실기동에서 MCP 서버가 DB 조회에 성공한 것이 곧 `MSSQL_*` 전달의 실증.

## 5. 기존 흐름 회귀 스모크

- **PDF 리포트**: `POST /api/report/pdf`(프록시 경유) → HTTP 200, `application/pdf`, 3,603 bytes, 매직넘버 `%PDF-1.4` 정상. `Content-Disposition`의 `filename*=UTF-8''...` 한글 파일명 인코딩 정상.
- **기존 매출 조회 흐름**: 실기동 2가 곧 이 경로(뷰 목록 → 스키마 → 별칭 → 조회 → 표+차트)의 전체 회귀 확인.
- **MCP 세션 개폐 구조**: `run_chat()`의 `finally: await mcp_client.__aexit__(...)`(`gemini_agent.py:129-130`) 유지. 라운드 루프는 단일 세션 내부 반복이므로 상한 변경이 세션 수명에 영향 없음 — 06 요약의 판단이 코드와 일치함을 확인.

## 6. 관측 사항 (이번 변경의 결함 아님 / 후속 권고)

### (A) `SALES_DT`가 날짜가 아닌 `'YYYY-MM'` 문자열 — 라운드 예산의 주 소비자

**우선순위: 중(기능 정확성). 이번 변경으로 생긴 문제가 아니라, 상향된 라운드 여유를 즉시 잠식하는 선행 이슈.**

실기동 1에서 9회 중 **4회가 동일 목적의 실패 재시도**였다. DB 직접 확인 결과:

```
SELECT TOP 3 SALES_DT, LEN(SALES_DT) AS L FROM dbo.JINJU_SALES
-> [{'SALES_DT': '2026-06', 'L': 7}, ...]
```

- `SALES_DT`는 `nvarchar`이며 값이 **`'2026-06'` (길이 7, 월 단위)** 이다.
- `CAST(SALES_DT AS DATE)` → `pyodbc.DataError 22007 "문자열을 날짜 및/또는 시간으로 변환하지 못했습니다"` (실행 실패)
- `TRY_CONVERT(DATE, SALES_DT)` → 예외는 없으나 **전 행 `NULL`** 반환 (조용한 오답)
- `SUBSTRING(SALES_DT, 1, 7)` → 정상 (실기동 2가 우연히 이 형태를 골라 성공)

즉 모델은 `get_view_schema`가 돌려주는 `nvarchar`라는 정보만으로 실제 값 형식을 알 수 없어 날짜 파싱 방식을 라운드마다 바꿔가며 추측한다. 실기동 1은 이 추측에만 4라운드(약 26초)를 썼고, 그 결과 10라운드를 소진하고도 월별 추이를 산출하지 못했다.

**재현**: 실기동 1 질문("지점별 매출 합계 상위 3곳과, 그 3곳의 최근 월별 매출 추이를 함께 알려줘")을 그대로 재전송.

**수정 제안(둘 중 하나, backend-dev 범위)**: `backend/app/config.py`의 SYSTEM_PROMPT MSSQL 항목 바로 뒤에 데이터 형식 힌트를 1줄 추가.

```
- 날짜/기간 컬럼(예: SALES_DT)이 nvarchar인 경우 값이 이미 'YYYY-MM' 같은 문자열일 수 있다.
  CAST/CONVERT로 DATE 변환을 시도하기 전에 먼저 소량(SELECT TOP 5 ...)으로 실제 값 형식을
  확인하고, 문자열이면 SUBSTRING/LEFT로 직접 다루어라. TRY_CONVERT는 실패해도 NULL을
  돌려주므로 결과가 전부 NULL이면 변환 방식이 틀린 것으로 판단하라.
```

이 한 줄이 실기동 1의 4라운드 낭비를 제거하면 해당 질문은 5~6라운드로 수렴해 상한 10에 실질적 여유가 생긴다.
(대안: `get_view_schema` 응답에 샘플 값을 포함시키는 방식 — 다만 이는 `mcp_server/server.py` 수정이므로 mcp-guardian 범위이고, 뷰 데이터 노출 정책 검토가 별도로 필요하다. 프롬프트 수정을 우선 권고.)

### (B) PDF `Content-Disposition` ASCII 폴백이 공백 문자열

`main.py:76`의 `ascii_fallback`이 순수 한글 제목에서 `"  .pdf"`(공백만 남음)가 된다. `filename*=UTF-8''`가 함께 있어 현대 브라우저는 모두 정상 동작하므로 **기능 영향 없음**. 폴백이 공백뿐이면 `"sales_report.pdf"`로 대체하도록 조건을 `or` 앞에서 `.strip()` 검사로 바꾸면 더 견고하다. 우선순위 낮음, 이번 변경과 무관.

---

## 최종 판정

지시된 검증 항목 1~5 **전부 통과**. `MAX_TOOL_ROUNDS = 10`과 SYSTEM_PROMPT의 MSSQL 방언 지시는 회귀 없이 의도한 효과를 내고 있으며, 프론트 프록시 타임아웃 대비 안전 여유도 실측으로 확인됐다. §6(A)는 이번 변경과 독립적인 후속 개선 권고이며 릴리스 차단 사유가 아니다.
