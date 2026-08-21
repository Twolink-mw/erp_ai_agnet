---
name: sql-guardrail-review
description: "매출 뷰 화이트리스트(views_whitelist.py), SQL 가드(sql_guard.py), DB 연결(db.py) 변경 시 defense-in-depth 체인 전체를 검토하는 절차. 새 매출 뷰 추가, 한글 별칭 추가, 금지 키워드/정규식 수정, MCP run_sql 도구 수정 시 반드시 이 스킬을 따를 것. 단순 오타 수정이라도 이 세 파일을 건드리면 적용한다."
---

# SQL Guardrail Review

매출 데이터 접근 통제는 세 파일이 순서대로 방어하는 체인이다: **별칭 치환 → 키워드 검사 → 테이블 참조 검사 → 행수 제한 → DB 계정 권한**.
하나를 느슨하게 바꾸면 정규식 하나는 통과해도 체인 전체에서는 뚫릴 수 있다. 그래서 변경 시 항상 체인 전체를 다시 추적한다.

## 체인 구조

```
사용자 자연어 질문
  → Gemini가 SQL 생성 (별칭 사용 가능, 예: "매출액", "거래처")
  → rewrite_query_with_aliases()  [views_whitelist.py]  — 한글 별칭을 실제 뷰/컬럼명으로 치환
  → validate_and_prepare()        [sql_guard.py]
      1. 다중 문장(;) 차단
      2. SELECT 이외 차단
      3. 금지 키워드 차단 (DML/DDL, xp_cmdshell, sp_executesql, OPENROWSET 등)
      4. 모든 FROM/JOIN 대상을 SALES_VIEW_WHITELIST와 대조
      5. TOP 절 없으면 TOP 1000 자동 삽입
  → db.py가 MSSQL_READONLY_USER로 실행 (화이트리스트 뷰에 대해서만 SELECT 권한 있다고 전제)
```

## 새 매출 뷰를 추가할 때

1. `views_whitelist.py`의 `SALES_VIEW_WHITELIST`에 `schema.view` 형식으로 **명시적으로** 추가한다. 패턴 매칭이나 스키마 전체 허용으로 대체하지 않는다.
2. 그 뷰가 매출과 무관한 데이터(인사/급여/개인정보)를 포함하지 않는지 확인한다. 조금이라도 불확실하면 추가하지 않고 사용자에게 확인한다.
3. 필요하면 `VIEW_ALIASES`에 한글 별칭을 추가한다. 컬럼 별칭이 필요하면 `COLUMN_ALIASES`에 추가한다.
4. `sql_guard.py`의 테이블 참조 검사가 새 뷰의 스키마.뷰 표기(대소문자, 대괄호 `[schema].[view]` 등)를 실제로 매칭하는지 확인한다 — 화이트리스트 문자열 형식과 SQL 파싱 결과의 형식이 다르면 정상 뷰인데도 거부되거나, 반대로 검사를 우회할 수 있다.
5. `MSSQL_READONLY_USER`가 이 뷰에 대한 SELECT 권한을 실제로 가지고 있는지는 앱 코드가 강제하지 않는 운영 전제조건이다 — 사용자에게 DB 계정 권한 부여가 별도로 필요하다는 점을 알린다.
6. qa-verifier에게 새 뷰에 대한 우회 테스트(별칭 위장, 대소문자 변형)를 요청한다.

## sql_guard.py의 정규식/키워드 규칙을 수정할 때

정규식 하나만 보고 "이 패턴은 차단된다"고 판단하지 않는다. 다음 우회 경로를 항상 함께 검토한다:

- **주석 삽입**: `SELECT * FROM view -- ; DROP TABLE x` 같은 SQL 주석으로 검사를 회피하려는 시도
- **대소문자/공백 변형**: `ExEc`, `sp_execute sql`(공백 삽입), 유니코드 유사 문자
- **별칭 치환 순서**: 별칭 치환이 키워드 검사보다 먼저 실행되므로, 별칭 자체에 금지 키워드가 은닉될 수 있는지 확인 (`VIEW_ALIASES`/`COLUMN_ALIASES`는 하드코딩된 값이라 이 경로는 신뢰 가능하지만, 별칭 추가 시에도 값 자체를 검증한다)
- **다중 문장 우회**: 세미콜론이 아닌 다른 구분자(배치 구분자 `GO` 등)로 여러 문장을 실행하려는 시도
- **화이트리스트 매칭 우회**: 서브쿼리, CTE(`WITH`), 동적 SQL 문자열 내부에 비화이트리스트 테이블을 숨기는 시도 — CTE 문법 자체는 정식 지원되므로(`_parse_cte_definitions()`가 바깥쪽 최종 SELECT를 찾아 TOP을 삽입하고, CTE 이름은 화이트리스트 검사에서 예외 처리됨), 검토 대상은 "WITH가 있는가"가 아니라 "CTE 본문의 FROM/JOIN이 전부 화이트리스트를 통과하는가"다

수정 후 `backend/tests/test_sql_guard.py`를 반드시 실행하고, 위 우회 경로 중 이번 변경과 관련된 것에 대해 새 테스트 케이스를 추가한다.

## 체크리스트 (변경 완료 후)

- [ ] 화이트리스트 추가/변경이 `schema.view` 명시적 나열 형태를 유지하는가
- [ ] 새로 추가된 뷰/별칭이 매출 데이터만 포함하는가 (인사/급여/개인정보 아님)
- [ ] 별칭 치환 → 키워드 검사 → 테이블 참조 검사 → 행수 제한 순서가 유지되는가
- [ ] `backend/tests/test_sql_guard.py`, `test_views_whitelist.py` 통과
- [ ] 우회 시나리오(주석/대소문자/서브쿼리 은닉)를 최소 1개 이상 직접 테스트했는가
- [ ] backend-dev에게 변경 사항을 알렸는가 (시스템 프롬프트/도구 스키마 영향 가능)
