# 10. mcp-guardian — DISTINCT 쿼리 TOP 자동 삽입 버그 수정

## 결론 요약
버그는 실재했고 수정했다. 다만 **작업 지시에 포함된 T-SQL 문법 전제는 사실과 반대였다.**

## 전제 정정 (실측)
**정정 대상은 09 리포트가 아니라, 나에게 전달된 작업 지시문이다.**
09 리포트(§4)의 T-SQL 문법 기술과 수정 제안은 원래부터 **정확했다**. 전달 과정에서 문법이 뒤집혔다.

뒤집힌 지시문: "T-SQL은 반드시 `DISTINCT`가 `TOP`보다 뒤에 와야 한다 (`SELECT TOP n DISTINCT ...`가 맞다)"

실제 MSSQL(dbo.JINJU_SALES, ODBC Driver 18)로 직접 실행해 확인한 결과:

| 쿼리 | 결과 |
|---|---|
| `SELECT DISTINCT TOP 3 SALES_DT FROM dbo.JINJU_SALES` | **성공** (3 rows) |
| `SELECT TOP 3 DISTINCT SALES_DT FROM dbo.JINJU_SALES` | **실패** — SQL Server 오류 156 (`'DISTINCT' 근처 문법 오류`) |

T-SQL select 절 문법은 `SELECT [ALL | DISTINCT] [TOP (n)] <select_list>` 이다.
즉 **TOP이 DISTINCT 뒤**에 와야 한다. 지시문 요구사항 1의 "TOP을 SELECT 바로 뒤, DISTINCT보다 앞에 삽입"을 그대로 구현했다면
`SELECT TOP 1000 DISTINCT ...` — 즉 리포트가 "문법 오류"라고 지목한 바로 그 출력을 생성하게 된다(자기모순).
따라서 지시된 삽입 위치가 아니라 **실측으로 검증된 올바른 문법**을 기준으로 구현했다.

## 변경 파일
- `backend/mcp_server/sql_guard.py` — TOP 감지/삽입 로직
- `backend/tests/test_sql_guard.py` — DISTINCT 회귀 테스트 12건 추가

## 수정 내용 (sql_guard.py)
선택적 한정자 `(?:\s+(?:ALL|DISTINCT)\b)?` 를 감지·삽입 양쪽 패턴에 공통 적용.

- `_TOP_PATTERN`: `SELECT [ALL|DISTINCT] TOP n` 을 모두 인식 → 기존 TOP 중복 삽입 방지
- `_SELECT_PREFIX_PATTERN`(신규): SELECT + 한정자 직후에 TOP 삽입, 뒤따르는 공백을 흡수해 한 칸으로 정규화
  → `SELECT DISTINCT(COL)` 처럼 공백 없는 형태도 `SELECT DISTINCT TOP 1000 (COL)` 로 안전 삽입

세 경우 모두 처리:
| 입력 | 출력 |
|---|---|
| `SELECT DISTINCT TOP 10 x` | 변경 없음 (TOP 중복 없음) |
| `SELECT DISTINCT x` | `SELECT DISTINCT TOP 1000 x` |
| `SELECT x` | `SELECT TOP 1000 x` (기존 동작 유지) |

## 체인 정합성 (sql-guardrail-review 절차)
- 화이트리스트 변경 없음 — `SALES_VIEW_WHITELIST`는 `dbo.JINJU_SALES` 명시 나열 그대로. 뷰/별칭 추가 없음
- 파이프라인 순서 유지: 다중문장 → SELECT 검사 → 금지 키워드 → 별칭 치환 → 테이블 참조 검사 → **TOP 삽입(최종)**
  TOP 삽입은 파이프라인 마지막 단계이므로 `_check_and_qualify_table_refs`의 오프셋 기반 수식화에 영향 없음
- `ALL` 한정자 추가 인식이 `UNION ALL`에 영향 없음 확인 (패턴이 `^` 앵커)
- 컬럼명 `DISTINCTIVE_FLAG` 처럼 한정자 접두어를 가진 식별자 오인식 없음(`\b` 경계) — 테스트로 고정

## 우회 시나리오 실측 (전부 차단 확인)
DISTINCT를 얹은 우회 시도 7종 — 비화이트리스트 뷰(`dbo.HR_PAYROLL`), JOIN 은닉(`dbo.EMPLOYEE`),
주석 우회, 다중 문장, `SELECT ... INTO`, 서브쿼리 은닉(`dbo.SECRET`), 대소문자 변형 + UNION 은닉 — **모두 거부됨**.
DISTINCT 지원 추가로 새로 열린 우회 경로 없음.

## 테스트
- `backend/tests` 전체 pytest: **156 passed** (기존 144 + 신규 12)
- 실기동 MSSQL 검증: `SELECT DISTINCT SALES_DT FROM dbo.JINJU_SALES` 포함 8개 정상 쿼리가
  가드 통과 후 실제 MSSQL에서 **전부 성공 실행**

## config.py 임시 조치와의 상충 여부 (coordinator 요청)
backend-dev가 넣은 임시 조치(`config.py`에서 `SELECT DISTINCT TOP N` 예시 → `SELECT TOP n ... GROUP BY ...`)를
검토한 결과 **가드 수정과 충돌하지 않는다.** 그대로 둬도 무방하다.

- `SELECT TOP 10 <컬럼> FROM <뷰> GROUP BY <컬럼> ORDER BY <컬럼>` — 유효한 T-SQL이며 실기동 성공(3 rows).
  가드는 이미 `TOP n`이 있으므로 손대지 않는다. 중복 삽입 없음.
- DISTINCT를 피하는 방향이므로 수정된 가드와 기능적으로 겹칠 뿐 모순되지 않는다.

**다만 문구 하나는 손보는 편이 낫다 (backend-dev 소관):**
`config.py:28`의 "샘플 확인 쿼리는 항상 `SELECT TOP n`으로 시작한다"가, 모델이 DISTINCT를 쓰고 싶을 때
`SELECT TOP 5 DISTINCT ...`(= 문법 오류 156)로 유도할 수 있다. 이는 09 리포트 run#3 `#5`에서
실제로 관측된 모델 오작성 패턴이며, 실측으로 재확인했다:

```
guard-> SELECT TOP 5 DISTINCT SALES_DT FROM dbo.JINJU_SALES   (가드 무변형 — 이미 TOP n으로 시작)
   live FAIL 42000 (156)
```

가드는 이 형태를 고칠 수 없다(고쳐서도 안 된다 — 사용자 SQL의 의미 재작성이므로).
권장 문구: "DISTINCT를 함께 쓸 때는 `SELECT DISTINCT TOP n ...` 순서로 쓴다 (TOP이 DISTINCT 앞에 오면 오류)".

## 후속 필요
- backend-dev: 도구 스키마/시스템 프롬프트 구조 변경은 불필요(뷰·별칭 변화 없음).
  위 `config.py:28` 문구 보강만 검토 요청.
- 09번 리포트에 해결 표시 추기 완료. **리포트의 문법 기술은 옳으므로 수정하지 않았다.**
