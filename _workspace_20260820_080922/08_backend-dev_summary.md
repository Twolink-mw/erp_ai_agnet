# 08 backend-dev — nvarchar 날짜 컬럼 대응 프롬프트 지시 추가

대상: `backend/app/config.py` (`SYSTEM_PROMPT`) 단일 파일
근거: `_workspace/07_qa-verifier_report.md` §6A (`SALES_DT`가 `'2026-06'` 형태 nvarchar)

## 1. 변경 내용

`backend/app/config.py`의 `SYSTEM_PROMPT`에 날짜/기간 컬럼 형식 확인 지시 한 항목을 추가했다.
다른 파일 변경 없음. `backend/mcp_server/server.py`(도구 스키마)는 지시대로 손대지 않았다.

MSSQL 방언 항목 바로 뒤에 삽입:

```
- 날짜/기간을 뜻하는 컬럼이라도 get_view_schema가 알려주는 타입이 nvarchar/varchar이면,
  값이 이미 'YYYY-MM'이나 'YYYY-MM-DD' 같은 문자열일 수 있다. 타입만 보고 날짜라고 단정하지 말고,
  CAST/CONVERT/TRY_CONVERT로 DATE 변환을 시도하기 전에 먼저 실제 값 형식을 확인한다.
  - 확인 방법: `SELECT TOP 5 <컬럼> FROM <뷰>` 로 샘플을 보거나,
    `SELECT TOP 10 <컬럼> FROM <뷰> GROUP BY <컬럼> ORDER BY <컬럼>` 으로 고유값 패턴을 본다.
    (샘플 확인 쿼리는 항상 `SELECT TOP n`으로 시작한다.)
  - 값이 문자열 형식이면 DATE 변환 대신 SUBSTRING/LEFT 등 문자열 함수로 직접 다루고,
    정렬·그룹핑도 문자열 그대로 수행한다 (예: 월 단위는 `SUBSTRING(<컬럼>, 1, 7)`).
  - TRY_CONVERT/TRY_CAST는 변환에 실패해도 오류 없이 NULL을 돌려준다. 결과가 전부 NULL이거나
    집계가 비면 데이터가 없는 것이 아니라 변환 방식이 틀린 것으로 판단하고 다른 접근을 시도한다.
  - 이런 확인·재시도는 내부 과정일 뿐이므로, 최종 답변에는 시행착오나 실패한 쿼리를 언급하지 말고
    확인된 결과만 자연스럽게 전달한다.
```

07 리포트의 제안문을 그대로 쓰지 않고 일반화했다 — 컬럼명(`SALES_DT`)이나 특정 뷰를 하드코딩하면
새 뷰가 추가될 때 지시가 낡으므로, "nvarchar/varchar 타입의 날짜성 컬럼"이라는 조건으로 표현했다.

### 1-1. 09 qa-verifier 지적에 따른 후속 수정 (고유값 확인 예시)

최초 작성 시 고유값 확인 예시로 `SELECT DISTINCT TOP 10 <컬럼> FROM <뷰> ORDER BY <컬럼>`을 넣었으나,
09 검증에서 이 형태가 **가드를 통과하면 문법 오류가 되는 쿼리**임이 밝혀져 `GROUP BY` 형태로 교체했다.

원인은 `sql_guard.py:29`의 `_TOP_PATTERN`이 `SELECT` 직후의 `TOP`만 인식한다는 점이다.
`SELECT DISTINCT ...`는 매칭에 실패해 `sql_guard.py:220-221`이 `SELECT` 바로 뒤에 `TOP 1000`을 삽입한다.
직접 재현 확인:

```
IN : SELECT DISTINCT TOP 10 SALES_DT FROM dbo.JINJU_SALES ORDER BY SALES_DT
OUT: SELECT TOP 1000 DISTINCT TOP 10 SALES_DT FROM dbo.JINJU_SALES ORDER BY SALES_DT
IN : SELECT DISTINCT SALES_DT FROM dbo.JINJU_SALES
OUT: SELECT TOP 1000 DISTINCT SALES_DT FROM dbo.JINJU_SALES
```

T-SQL은 `DISTINCT`가 `TOP`보다 앞서야 하므로 둘 다 42000 구문 오류가 된다.
교체한 `GROUP BY` 형태와 기존 `SELECT TOP 5` 형태는 가드를 **원문 그대로 통과**함을 확인했다.

이 수정은 프롬프트가 실패하는 쿼리를 권장하지 않게 만드는 것일 뿐, **가드 결함 자체를 고치는 것이 아니다.**
`run_sql`에 들어오는 모든 `DISTINCT` 쿼리는 여전히 명시적 `SELECT TOP n`으로 시작하지 않는 한 실행 불가다.
`sql_guard.py` 수정은 mcp-guardian 소관이므로 별도 과제로 남긴다(§5).

**날짜 형식 확인 지시 한 항목이 이번 변경의 전부다.** 작업 도중 실기동에서 관측된 수치 날조 문제(§5)에 대해
"모든 수치는 run_sql 결과여야 한다"는 가드를 임시로 추가했다가, 이번 범위 밖이라는 결정에 따라
제거했다. 최종 `SYSTEM_PROMPT`에는 위 날짜 형식 지시만 들어 있다.

## 2. 기존 지시와의 상충 검토

| 기존 지시 | 상충 여부 | 근거 |
|---|---|---|
| 한글 별칭 해석(`get_view_aliases`/`get_column_aliases`) | 없음 | 추가분은 값 *형식*에 대한 지시로 이름 해석 단계와 직교. 실기동에서 별칭 조회 호출 유지 확인 |
| ` ```chart ` 블록 출력 | 없음 | 블록 지시 원문 무수정. 실기동 전건 chart 블록 정상 출력 |
| MSSQL `TOP` 사용(LIMIT 금지) | 없음 | 추가한 예시 쿼리도 `SELECT TOP 5` / `SELECT DISTINCT TOP 10` 형태로 통일 |
| PDF 요청 시 재쿼리 금지 | 없음 | 추가분은 "SQL을 새로 작성할 때"의 지침. `/api/report/pdf`는 LLM을 거치지 않는 순수 렌더링 엔드포인트(`main.py:62-73`)라 프롬프트 영향 자체가 없음 |

`gemini_agent.py`, `mcp_client.py`, `MAX_TOOL_ROUNDS`(10) 무수정 — MCP 세션 1턴 1개 구조와
`env=dict(os.environ)` 전체 환경변수 전달도 그대로다.

## 3. pytest 결과

`backend\.venv\Scripts\python.exe -m pytest backend/tests -q`

- **144 passed** in 4.99s (최종 상태 = 날짜 지시만 포함, DISTINCT 예시 교체 반영)

회귀 없음. `SYSTEM_PROMPT` 문자열을 단언하는 테스트는 없음(`grep SYSTEM_PROMPT` → `config.py` 정의부와
`gemini_agent.py:6,87` 사용부뿐)이라 프롬프트 편집이 테스트 계약을 건드리지 않는다.

## 4. 실기동 확인

백엔드는 편집 반영을 위해 재기동(venv python, `--port 8000`), 요청은 프론트 프록시(`localhost:3000/api/chat`) 경유.
아래는 최종 상태(날짜 지시만 적용)에서의 실행 결과다.

| # | 질문 | 결과 | 도구 호출 | 소요 |
|---|---|---|---|---|
| 07 기준(변경 전) | 지점별 상위 3곳 + 월별 추이 | 월별 추이 **산출 실패**(라운드 10/10 소진, 실패 재시도 4회) | 9 | 64.7s |
| 1 | 동일 질문 | **정상**, 실패 호출 0 | 5 | 43.0s |
| 2 | 최근 월별 매출 추이 | 표/차트 정상, 수치 정확 | 5 | 40.4s |
| 3 | 동일 질문(최종 상태 재확인) | **정상**, 실패 호출 0 | 6 | 24.2s |
| 4 | 동일 질문(DISTINCT 예시 교체 후) | **정상**, 실패 호출 0, 상위 3곳 + 월별 추이 모두 응답 | 7 | 32.6s |

핵심 관측:

- **날짜 파싱 시행착오 완전 소멸.** 07에서 4라운드를 잡아먹던 `CAST`/`TRY_CONVERT` 실패 재시도가
  실기동 전건에서 **0건**. 모델은 `SUBSTRING(SALES_DT, 1, 7)`을 1차 시도에 바로 사용하거나,
  run#3처럼 `SELECT TOP 5 SALES_DT` 샘플 확인 1회(성공 호출)를 거친 뒤 곧장 올바른 쿼리를 만든다.
- **라운드 예산 회복.** 동일 질문 기준 9회 → 5~6회. `proxyTimeout: 120_000` 대비 여유는 24.2~43.0s로
  07의 64.7s보다 개선.
- **chart 블록 계약 유지.** `{"type":"line","title":...,"xKey":...,"series":[...],"data":[...]}` 형태로
  출력되어 `ChartRenderer.tsx`의 `parseChartSpec` 검증 조건을 충족. 프론트 계약 변경 없음 →
  frontend-dev에 통보 불필요.
- **답변에 시행착오 미노출.** 샘플 확인 쿼리를 거친 경우에도 최종 답변에 해당 언급 없음.

수치 교차 검증: 월별 합계(2026-06 8,966,834,595 / 07 8,527,473,886 / 08 9,510,176,777)가 반복 실행 간 일치.

## 5. 후속 검토 대상 (이번 범위 제외)

- **`sql_guard.py`의 DISTINCT 처리 결함 (mcp-guardian 소관, 우선순위 높음)** — §1-1 참조.
  `run_sql`에 들어오는 `SELECT DISTINCT ...`는 명시적 `TOP n`이 없으면 가드가 `SELECT TOP 1000 DISTINCT ...`로
  재작성해 항상 T-SQL 구문 오류가 된다. 프롬프트에서 DISTINCT 예시를 뺐으므로 모델이 이 형태를 생성할
  빈도는 줄지만, 결함 자체는 남아 있어 모델이 자발적으로 DISTINCT를 쓰면 그대로 라운드를 소모한다.
  09 리포트의 제안(정규식에 `(?:DISTINCT\s+|ALL\s+)?` 허용 + DISTINCT 뒤에 TOP 삽입하도록 분기 +
  `test_sql_guard.py`에 DISTINCT 회귀 케이스 추가)이 적절해 보인다. 이 파일은 backend-dev 범위가 아니므로
  수정하지 않았다.
- **`get_view_schema` 응답에 샘플값 포함** — 지시대로 이번 범위에서 제외. `mcp_server/server.py` 변경이라
  mcp-guardian 소관이며 뷰 데이터 노출 정책 검토가 선행되어야 한다. 프롬프트 지시만으로 실측 효과가
  확인됐으므로(§4) 우선순위는 낮아졌다. 다만 컬럼 타입만으로 값 형식을 알 수 없는 구조적 한계 자체는
  남아 있어, 새 뷰가 늘어나면 재검토 가치가 있다.
- **수치 날조 관측 (별도 과제로 이관)** — 이번 작업 중 실기동 1건에서, 모델이 집계 `run_sql`을 실행하지
  않은 채 매출 수치를 지어낸 응답을 관측했다("최근 월별 매출 추이" 질문에 12억/13억/14억대 반환,
  실제값은 89억/85억/95억대). 도구 호출 로그상 `list_sales_views` → `get_view_schema` →
  `SELECT TOP 5 SALES_DT`(샘플) → `get_column_aliases`까지만 실행되고 집계 쿼리가 없었다.
  동일 질문 재실행 시에는 재현되지 않아 확률적 현상으로 보인다. 이번 범위에서는 대응하지 않기로 결정됐고,
  필요 시 별도 요청으로 다룬다. 데이터 정확성 영향이 크므로 qa-verifier의 반복 실행 재현율 확인을 권고한다.
- 07 §6B(PDF `Content-Disposition` ASCII 폴백 공백) — 미착수. `main.py:76`이 이미
  `or "sales_report.pdf"` 폴백을 갖고 있으나 공백만 남는 경우는 truthy라 폴백이 걸리지 않는다.
  기능 영향 없음, 우선순위 낮음.

## 6. 실행 환경 메모

기존에 떠 있던 uvicorn은 `--reload` 없이 기동돼 있어 프롬프트 편집이 반영되지 않았다.
검증을 위해 `backend/.venv`의 python으로 재기동했다(현재 8000 포트에서 최종 상태 코드로 동작 중).
시스템 python에는 uvicorn이 설치돼 있지 않으므로 venv 인터프리터로 기동해야 한다.
