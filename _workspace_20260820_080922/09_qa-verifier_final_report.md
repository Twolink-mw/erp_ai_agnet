# 09 qa-verifier — 최종 검증 리포트 (날짜 형식 nvarchar 프롬프트 보강)

대상: `backend/app/config.py` (`SYSTEM_PROMPT`) 최종본
근거 문서: `_workspace/08_backend-dev_summary.md`, `_workspace/07_qa-verifier_report.md`

**판정: 조건부 통과 — 프롬프트 변경 자체는 정상이나, 새 지시가 권장하는 `SELECT DISTINCT`
패턴이 `sql_guard.py`의 TOP 자동 삽입과 충돌해 실기동에서 실패 쿼리를 유발한다 (§4).**

---

## 1. 테스트 스위트

| 스위트 | 명령 | 결과 |
|---|---|---|
| pytest | `backend\.venv\Scripts\python.exe -m pytest backend/tests -q` | **144 passed** in 4.70s |
| vitest | `cd frontend; npm test` | **32 passed** (2 files) — `Chat.test.tsx` 17, 나머지 15 |

08 산출물의 "144 passed" 주장은 독립 재실행으로 확인됨. 회귀 없음.
(vitest 로그의 `act(...)` 경고는 기존부터 있던 것으로 실패가 아님.)

## 2. 롤백 확인 — "수치는 run_sql 결과여야 한다" 가드 제거 여부

`backend/app/config.py` 전문(58줄)을 직접 읽어 확인. **깔끔하게 제거됨.**

- `SYSTEM_PROMPT` 안에 "run_sql 결과", "수치를 지어내지", "날조" 류 문구 **없음**.
- 날짜 지시는 `config.py:23-33` 한 항목으로만 존재하며, 08 요약 §1의 인용문과 문자 단위로 일치.
- `git diff backend/app/config.py` 상 추가분은 (a) MSSQL TOP/OFFSET 항목(01/06 단계 산출), (b) 날짜 지시,
  (c) PDF 재정리 항목(06 단계 산출) 3개뿐 — 이번 단계에서 새로 들어간 것은 (b) 하나.
- 편집 잔재(중복 항목, 끊긴 불릿, 들여쓰기 붕괴) 없음.

## 3. 기존 지시와의 상충 (프롬프트 내부)

| 기존 지시 | 위치 | 판정 |
|---|---|---|
| 한글 별칭 해석 | `config.py:34-36` | 상충 없음. 실기동에서 `get_column_aliases` 호출 유지 확인 |
| ` ```chart ` 블록 스키마 | `config.py:40-48` | 상충 없음. 원문 무수정 |
| MSSQL `TOP` 사용(LIMIT 금지) | `config.py:20-22` | **프롬프트 내부는 상충 없음. 단, 가드 계층과는 충돌 — §4 참조** |
| PDF 요청 시 재쿼리 금지 | `config.py:50-57` | 상충 없음. `/api/report/pdf`(`main.py:62-89`)는 LLM을 거치지 않는 순수 렌더링 경로 |

`SYSTEM_PROMPT` 문자열을 단언하는 테스트는 없음 → 프롬프트 편집이 테스트 계약을 건드리지 않음(08 §3 확인).

## 4. 발견된 문제 — `SELECT DISTINCT` + TOP 자동 삽입 충돌 (신규, ~~미해결~~ → **해결됨**)

**심각도: 중 (기능 오류, 보안 영향 없음)**

> **[2026-08-20 mcp-guardian 추기 — 해결]**
> 이 절의 진단과 수정 제안(§4 "수정 제안" 1·2·3)은 **모두 정확했고**, 그대로 반영해 수정 완료했다.
> 특히 line 77의 T-SQL 문법 기술(`DISTINCT`가 `TOP`보다 앞서야 한다)은 **옳다** —
> 재실측으로 재확인했다: `SELECT DISTINCT TOP 3 ...` 성공 / `SELECT TOP 3 DISTINCT ...` 오류 156.
> (중간 전달 과정에서 이 문법이 반대로 뒤집혀 재전달된 적이 있으나, 원 리포트에는 오류가 없다.
> 이후 이 절을 인용할 때 뒤집지 말 것.)
>
> - 수정: `backend/mcp_server/sql_guard.py` — `_TOP_PATTERN`에 선택적 `ALL|DISTINCT` 한정자 인식 추가,
>   신규 `_SELECT_PREFIX_PATTERN`으로 한정자 **뒤**에 TOP 삽입
> - 회귀 테스트: `backend/tests/test_sql_guard.py`에 DISTINCT 케이스 12건 추가 (제안된 3건 포함)
> - `backend/tests` 전체 156 passed / 실기동 MSSQL 검증 완료
> - 상세: `_workspace/10_mcp-guardian_summary.md`
>
> 남은 사항 2건:
> 1. line 49가 인용한 `config.py:27`의 `SELECT DISTINCT TOP 10 ...` 예시는 그 후 backend-dev가
>    `SELECT TOP 10 <컬럼> ... GROUP BY ...` 형태로 교체했다(임시 조치). 인용은 리포트 작성 시점 기준.
> 2. line 87의 `#5 SELECT TOP 5 DISTINCT ...`(모델 자체 오작성)는 **가드가 고칠 수 없는 잔존 실패 모드**다.
>    이미 `TOP n`으로 시작하므로 가드는 정상으로 보고 손대지 않으며, MSSQL에서 156으로 실패한다.
>    → 프롬프트 측 대응 필요(§ 10번 요약 "후속 필요" 참조).

### 무엇이 무엇과 불일치하는가

- `backend/app/config.py:27` — 새로 추가된 날짜 지시가 값 형식 확인 방법으로
  `SELECT DISTINCT TOP 10 <컬럼> FROM <뷰> ORDER BY <컬럼>` 을 **명시적으로 권장**한다.
- `backend/mcp_server/sql_guard.py:29` — `_TOP_PATTERN = re.compile(r"^\s*SELECT\s+TOP\s*\(?\s*\d+\s*\)?", ...)`
  은 `SELECT` 직후의 `TOP`만 인식한다. `DISTINCT`가 사이에 끼면 매칭 실패.
- `backend/mcp_server/sql_guard.py:220-221` — 매칭 실패 시 `SELECT` 바로 뒤에 `TOP 1000`을 삽입한다.

결과적으로 프롬프트가 권장하는 쿼리가 **가드를 통과하면서 문법이 깨진 SQL로 변형된다.**

### 재현 (검증 완료)

`validate_and_prepare()` 직접 호출:

```
IN : SELECT DISTINCT TOP 10 SALES_DT FROM dbo.JINJU_SALES ORDER BY SALES_DT
OUT: SELECT TOP 1000 DISTINCT TOP 10 SALES_DT FROM dbo.JINJU_SALES ORDER BY SALES_DT   ← 문법 오류

IN : SELECT DISTINCT SALES_DT FROM dbo.JINJU_SALES
OUT: SELECT TOP 1000 DISTINCT SALES_DT FROM dbo.JINJU_SALES                            ← 문법 오류
```

MSSQL 실측(`run_readonly_query`, 읽기 전용 SELECT):

```
ERR SELECT TOP 1000 DISTINCT SALES_DT FROM dbo.JINJU_SALES
    -> [SQL Server] 키워드 'DISTINCT' 근처의 구문이 잘못되었습니다. (156)
OK  SELECT DISTINCT TOP 10 SALES_DT FROM dbo.JINJU_SALES ORDER BY SALES_DT
    -> [{'SALES_DT': '2026-06'}, {'SALES_DT': '2026-07'}, {'SALES_DT': '2026-08'}]
```

즉 T-SQL 문법상 `DISTINCT`가 `TOP`보다 앞서야 하는데, 가드는 항상 `TOP`을 맨 앞에 넣는다.
**`run_sql`을 통한 모든 `DISTINCT` 쿼리는 명시적 `SELECT TOP n`으로 시작하지 않는 한 실행 불가다.**
(이 결함은 `sql_guard.py`에 원래 있던 것이지만, `config.py:27`이 모델을 정확히 이 패턴으로 유도하면서
비로소 상시 도달 가능해졌다. 기존 `backend/tests/test_sql_guard.py`에 `DISTINCT` 케이스 0건.)

### 실기동 관측 (§5 run#3)

"지점별 매출 상위 3곳과 월별 매출 추이" 질의에서 8회 도구 호출 중 **2회가 이 오류로 소모**:

```
#5 run_sql SELECT TOP 5 DISTINCT SALES_DT ...      -> 42000 DISTINCT 구문 오류 (모델 자체 오작성)
#6 run_sql SELECT DISTINCT TOP 5 SALES_DT ...      -> 가드가 SELECT TOP 1000 DISTINCT TOP 5 로 변형, 42000 오류
#7 run_sql SELECT TOP 5 SALES_DT ...               -> 성공 (DISTINCT 포기 후 우회)
```

부수 피해: 라운드를 낭비한 결과 최종 답변에서 **"지점별 상위 3곳"이 통째로 누락**됐다
(#4에서 데이터를 이미 받았음에도 월별 추이만 응답). MAX_TOOL_ROUNDS(10) 초과는 아니었으나 근접.

### 수정 제안

`backend/mcp_server/sql_guard.py` 두 곳:

1. `:29` — `DISTINCT`/`ALL` 선행을 허용
   ```python
   _TOP_PATTERN = re.compile(r"^\s*SELECT\s+(?:DISTINCT\s+|ALL\s+)?TOP\s*\(?\s*\d+\s*\)?", re.IGNORECASE)
   ```
2. `:220-221` — `DISTINCT`가 있으면 그 **뒤**에 TOP을 삽입
   ```python
   if not _TOP_PATTERN.match(q):
       if re.match(r"^\s*SELECT\s+DISTINCT\b", q, re.IGNORECASE):
           q = re.sub(r"^\s*SELECT\s+DISTINCT\b", f"SELECT DISTINCT TOP {MAX_ROWS}", q, count=1, flags=re.IGNORECASE)
       else:
           q = re.sub(r"^\s*SELECT\b", f"SELECT TOP {MAX_ROWS}", q, count=1, flags=re.IGNORECASE)
   ```
3. `backend/tests/test_sql_guard.py`에 회귀 케이스 3건 추가:
   `SELECT DISTINCT c FROM v` → `SELECT DISTINCT TOP 1000 ...`,
   `SELECT DISTINCT TOP 10 c FROM v` → 무변형,
   `SELECT TOP 5 c FROM v` → 무변형.

**소관: `sql_guard.py`는 mcp-guardian 영역.** 대안으로 `config.py:27`에서 `DISTINCT` 예시를 빼는
프롬프트-only 우회도 가능하나, 가드 결함 자체는 남으므로 권장하지 않는다.

## 5. 실기동 검증 (07/08 재현 질문)

백엔드 :8000, 프론트 :3000 기동 상태. 요청은 프론트 프록시(`localhost:3000/api/chat`) 경유.

| # | 질문 | 소요 | 도구 호출 | 실패 호출 | 결과 |
|---|---|---|---|---|---|
| 1 | 최근 월별 매출 추이 | 41.3s | 7 | 0 | 정상, 수치 일치 |
| 2 | 최근 월별 매출 추이 (재실행) | 35.0s | 5 | 0 | 정상 — `SELECT TOP 5 SALES_DT` 샘플 1회 → `GROUP BY SALES_DT` 직행 |
| 3 | 지점별 상위 3곳 + 월별 추이 | 49.6s | 8 | **2** | 월별 추이 정상, **지점별 부분 누락** (§4) |

- **날짜 파싱 시행착오: 0건.** 3건 전부 `CAST`/`CONVERT`/`TRY_CONVERT` 시도 없음.
  모델은 `SELECT TOP 5 SALES_DT` 샘플 확인 후 `SALES_DT`를 문자열 그대로 `GROUP BY`한다.
  07에서 4라운드를 소모하던 날짜 변환 실패 재시도는 **재현되지 않음** → 이번 변경의 목적은 달성.
- **run#3의 실패 2건은 날짜 변환이 아니라 `DISTINCT` 문법 문제**(§4)로, 원인이 다르다.
- **수치 교차 검증**: 3건 모두 2026-06 `8,966,834,595` / 07 `8,527,473,886` / 08 `9,510,176,777` 로
  08 산출물과 완전 일치. 08 §5에서 관측된 12억/13억대 수치는 재현되지 않음.
- **답변에 시행착오 미노출**: 샘플 확인 쿼리·실패 쿼리 모두 최종 답변에 언급 없음. 지시대로 동작.

## 6. 경계면 정합성 (전체 체크리스트)

| 항목 | 판정 | 비고 |
|---|---|---|
| 화이트리스트 ↔ SQL 가드 | 통과 | `SALES_VIEW_WHITELIST`의 `dbo.JINJU_SALES`가 `_check_and_qualify_table_refs`를 정상 통과 |
| 별칭 치환 → 키워드 → 테이블 검사 순서 | 통과 | `SELECT DISTINCT TOP 10 매출일 FROM 매출` → `... SALES_DT FROM dbo.JINJU_SALES` 치환 확인 (단 TOP 변형 결함은 §4) |
| 가드 우회 시도 차단 | 통과 | 다중 문장 → "다중 SQL 문장은 허용되지 않습니다", 비화이트리스트 뷰 → 거부, CTE 우회 → "SELECT 문만 허용됩니다" |
| MCP 도구 5개 ↔ Gemini FunctionDeclaration | 통과 | `server.py:34-73`에 5개 정의, `gemini_agent.py:43-53`이 `list_tools()` 결과를 **동적 변환**(하드코딩 없음) |
| chart 스키마 (백엔드 ↔ 프론트) | 통과 | `config.py:41-43` `{type,title,xKey,series[{key,name}],data}` ↔ `ChartRenderer.tsx:19-24, 49-57` `parseChartSpec` 검증 조건 일치. 실기동 3건 전부 파싱 조건 충족 |
| 환경변수 전달 | 통과 | `mcp_client.py:35` `env=dict(os.environ)` — MSSQL_*/GEMINI_* 전량 상속 |

## 7. 이번 범위 외

- **수치 날조 관측 (08 §5)** — 별도 과제로 남아 있음. 이번 검증에서는 재현/수정을 시도하지 않았고,
  실기동 3건에서는 우연히 재현되지 않았다(재현율 측정 아님).
- 07 §6A `get_view_schema` 샘플값 포함, 07 §6B PDF `Content-Disposition` ASCII 폴백 공백 — 미착수 유지.

## 8. 검증 환경

- pytest: `backend\.venv\Scripts\python.exe` (시스템 python에는 uvicorn/의존성 미설치)
- DB 접속 확인은 `.env` 존재 확인 후, 화이트리스트 뷰 대상 **읽기 전용 SELECT 2건**만 수행.
  `backend/scripts/*` 수동 점검 스크립트는 실행하지 않음.
