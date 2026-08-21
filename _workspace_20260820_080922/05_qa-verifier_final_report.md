# 05 · qa-verifier — SQL 가드 비수식 테이블명 수정 독립 재검증

**최종 판정: 통과 (PASS)** — 1차 재검증에서 4건 발견 → mcp-guardian 수정 → 2차 재검증 전부 통과.

## 1. 테스트 스위트 (직접 재실행)

| 스위트 | 명령 | 1차 (수정 전) | 2차 (수정 후) |
| --- | --- | --- | --- |
| pytest | `python -m pytest backend/tests -q` (루트) | **129 passed** (자기 보고와 일치) | **144 passed** (+15) |
| vitest | `cd frontend && npm test` | **32 passed** (2 files) | 백엔드 전용 변경, 재실행 불요 |

## 2. 자체 우회/회귀 프로브 (58케이스)

| 구분 | 케이스 | 2차 결과 |
| --- | --- | --- |
| 우회 시도 (BLOCK 기대) | 34 | **34/34 차단** |
| 정상 쿼리 (ALLOW 기대) | 24 | **24/24 허용** |

1차에서는 우회 3건 통과 + 정상 2건 오탐 = 5건 불일치였다.

## 3. 1차 재검증에서 발견한 문제와 처리 결과

### F1 (HIGH · 보안) — APPLY 뒤 테이블 참조가 검사되지 않음 → **수정됨**
- 위치: `backend/mcp_server/sql_guard.py` `_FROM_JOIN_PATTERN`
- 통과했던 쿼리: `... CROSS APPLY HR.Payroll p`, `... CROSS APPLY dbo.Employee b`,
  `... CROSS APPLY SecretTable b`, `... OUTER APPLY dbo.SecretFn(a.BARCODE) b`
- 원인: `APPLY`가 구간 "종료" 키워드(`_CLAUSE_END_PATTERN`)에만 있고 구간 "시작" 키워드에는 없었다.
  T-SQL에서 APPLY 우변은 FROM/JOIN과 동일한 table_source라 임의 테이블명이 올 수 있다.
  이번 변경으로 새로 생긴 것은 아니지만("모든 테이블 참조를 검사한다"는 수정 목표와 정면 충돌) 함께 닫았다.
- 수정: `_TABLE_SOURCE_PATTERN = \b(?:FROM|JOIN|APPLY)\b`로 이름 변경 및 확장, `_CLAUSE_END_PATTERN`의 APPLY 유지.
- 재검증: 위 4건 + 소문자 `cross apply` + `OUTER APPLY (SELECT ... FROM SecretTable)` 전부 차단.
  화이트리스트 뷰만 쓰는 `CROSS APPLY (SELECT TOP 1 ... FROM dbo.JINJU_SALES) b`는 정상 허용.

### F2 (MEDIUM · 이번 변경의 회귀) — 문자열 리터럴/주석 안의 FROM·JOIN 오탐 → **수정됨**
- 차단됐던 정상 쿼리: `WHERE CUST_NM = 'JOIN Corp'`, `WHERE CUST_NM LIKE '%from%'`
  (각각 `'dbo.Corp''`, `'dbo.%''` 라는 엉뚱한 이름으로 거부)
- 원인: 구 정규식은 `schema.name` 형태를 요구해 리터럴 안에서 거의 매치되지 않았으나,
  새 파서는 `FROM`/`JOIN` 단어만 있으면 구간을 떴다. 실패 방향은 fail-closed라 보안 구멍은 아니지만
  제품명/거래처명 LIKE 조건 흐름에서 원인 불명의 차단으로 노출된다.
- 수정: `_NON_CODE_PATTERN` + `_mask_non_code()` 도입. 문자열 리터럴 / `--` 줄 주석 / `/* */` 블록 주석을
  **같은 길이의 공백**으로 치환한 사본에서 참조를 찾고(오프셋 1:1), 수식화 치환은 원본에 적용.
  대괄호 식별자를 먼저 소비해 `[we'ird]` 같은 식별자 안의 따옴표가 리터럴 스캔을 어긋내지 못하게 했다.
- 재검증: 리터럴 안 `from`/`join`/`APPLY`/이스케이프된 따옴표(`'O''Brien from Co'`)/한글 혼합 리터럴,
  본문 주석 전부 정상 허용. 반대로 마스킹을 이용한 은닉 시도 6종
  (`[x']`로 스캔 어긋내기, 빈 리터럴, `''` 이스케이프, `'['`, 블록 주석, `'/*'`) 전부 차단.

### F3 (MEDIUM · 기존 이슈) — `SELECT ... INTO`가 쓰기인데 통과 → **수정됨**
- 통과했던 쿼리: `SELECT * INTO SecretCopy FROM dbo.JINJU_SALES` (테이블 생성 = 쓰기)
- 수정: `_FORBIDDEN_KEYWORDS`에 `INTO` 추가. `SELECT ... INTO SecretCopy` / `INTO #t` 모두 차단 확인.

### F4 (LOW) — 대괄호 안에 점이 든 단일 식별자 → **수정됨**
- 통과했던 쿼리: `SELECT * FROM [dbo.JINJU_SALES]` (실제로는 실행 계정 기본 스키마의 `"dbo.JINJU_SALES"` 객체)
- 수정: `_split_identifier_parts()` 도입 — 대괄호/따옴표 안의 점은 구분자로 보지 않고,
  분해된 파트에 점이 남아 있으면 "해석할 수 없는 참조"로 거부.
- 재검증: `[dbo.JINJU_SALES]` / `[dbo.SecretTable]` 둘 다 거부, `[dbo].[JINJU_SALES]`는 정상 허용.

## 4. 경계면 정합성 (교차 비교)

| 경계면 | 판정 | 근거 |
| --- | --- | --- |
| 화이트리스트 ↔ SQL 가드 | 통과 | `dbo.JINJU_SALES`가 수식/비수식/대괄호/대소문자 변형 전부 통과. 비수식은 `dbo.`로 재작성되어 나감. APPLY 경로 포함 모든 table_source가 대조를 거침 |
| 별칭 치환 순서 | 통과 | 다중문장 → SELECT-only → 금지 키워드 → 별칭 치환 → 테이블 참조 검사 → TOP 삽입 순서 유지. `SELECT 매출액 FROM 매출` → `SALES_AMT` / `dbo.JINJU_SALES` 정상 |
| MCP 도구 ↔ Gemini FunctionDeclaration | 통과 | `gemini_agent.py:39-49`가 `list_tools()` 결과를 그대로 순회(하드코딩 없음). 실기동에서 도구 4종 사용 확인 |
| chart 스키마 (config.py ↔ ChartRenderer.tsx) | 통과 | `type/title/xKey/series[].key/data`가 `ChartRenderer.tsx:19-24, 54-57` `parseChartSpec` 기대와 일치. 실제 응답 chart 블록으로 확인 |
| 환경변수 전달 | 통과 | `mcp_client.py:35` `env=dict(os.environ)` — MSSQL_*/GEMINI_* 전부 상속 |
| PDF 리포트 (`/api/report/pdf`, `report_available`) | 통과 | `pdf_report.py`는 sql_guard와 결합 없음(요청 본문만 렌더링). 실기동 응답 2건 모두 `report_available: true` |

## 5. 엔드투엔드 실기동 검증

루트에서 `python -m uvicorn backend.app.main:app --port 8000` 기동 후 `POST /api/chat`.

| | 수정 전 | 수정 후 |
| --- | --- | --- |
| 질의 | "최근 매출 상위 제품명 5개를 매출액 기준으로" | "제품군별 매출액 합계를 상위 5개만 표와 차트로" |
| 결과 | HTTP 200, 13.5s | HTTP 200, 21.0s |
| 도구 호출 | list_sales_views → get_view_schema → get_column_aliases → run_sql ×2 | list_sales_views → get_column_aliases → run_sql ×2 |
| 실행 SQL | `SELECT TOP 5 ITEM_NM, SUM(SALES_AMT) ... GROUP BY ITEM_NM ORDER BY ...` | `SELECT TOP 5 ITEM_GROUP, SUM(SALES_AMT) ... GROUP BY ITEM_GROUP ORDER BY ...` |
| 응답 | 표 + chart 블록 + report_available=true | 표 + chart 블록 + report_available=true |

새 파서가 실제 Gemini 생성 쿼리(별칭 치환 후 형태)에 오탐을 내지 않고, 기존 TOP 유지 로직도 정상.

## 6. 잔여 관찰 사항 (블로커 아님)

1. **금지 키워드가 문자열 리터럴 안에서도 매치된다.** `WHERE CUST_NM = 'INTO Corp'`는 차단된다.
   단 이는 `INTO` 추가로 생긴 게 아니라 기존 `CREATE`/`DELETE` 등 모든 금지 키워드에 동일하게 존재하던
   fail-closed 동작이다(`'CREATE Co'`도 동일하게 차단). 원한다면 `_FORBIDDEN_KEYWORDS` 검사도
   `_mask_non_code()` 사본에서 수행해 일괄 해소 가능. 보안 방향은 안전(덜 허용) 쪽이라 이번 범위에서는 미조치.
2. **Gemini가 1차 시도에서 `LIMIT 5`를 생성한다** (실기동 2회 모두 재현). MSSQL이 거부하고 모델이
   스스로 `TOP 5`로 재시도해 복구하지만 왕복 1회와 수 초를 낭비한다. 가드와 무관한 프롬프트 이슈로,
   `SYSTEM_PROMPT`에 "MSSQL이므로 LIMIT 대신 TOP을 쓴다" 한 줄 추가를 backend-dev에게 권고.
3. **운영 전제**: `MSSQL_READONLY_USER`의 권한을 화이트리스트 뷰로 한정하는 3단째 방어는 코드가
   강제하지 않는다. DB 측 GRANT 점검이 여전히 필요하다 (mcp-guardian 보고와 동일 견해).
