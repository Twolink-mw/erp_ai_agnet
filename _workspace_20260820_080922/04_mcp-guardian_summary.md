# 04 · mcp-guardian — SQL 가드 비수식 테이블명 우회 수정

## 요약

| 항목 | 결과 |
| --- | --- |
| 재현된 우회 3건 | 전부 **REJECTED** |
| 추가로 발견·수정한 우회 | 콤마 구분 FROM 목록, 3부분 교차 DB 참조, 테이블 변수/임시 테이블 |
| 정상 쿼리 오탐 | 없음 (기존 케이스 + 파생 테이블/NOLOCK/한글 별칭 확인) |
| qa-verifier 재검증 지적 F1~F4 | **전부 수정** (7장 참조) |
| pytest (`backend/tests`) | **144 passed** (기존 117 + 신규 27) |
| MCP 도구 스키마 / 화이트리스트 / 별칭 | **변경 없음** → backend-dev 영향 없음 |

---

## 1. 근본 원인

`backend/mcp_server/sql_guard.py`의 구 `_TABLE_REF_PATTERN`:

```python
r"\b(?:FROM|JOIN)\s+\[?([A-Za-z0-9_]+)\]?\.\[?([A-Za-z0-9_]+)\]?"
```

`schema.name` 형태만 캡처한다. 비수식 이름(`FROM SecretTable`)은 매치 자체가 성립하지 않아
화이트리스트 대조 루프에 **들어가지도 않는다**. 단독 사용 시에는 `referenced`가 비어 차단되지만,
화이트리스트 뷰가 하나라도 함께 참조되면 검사가 성립한 것처럼 보이며 비수식 참조가 그대로 통과했다.

동일 원인으로 **콤마 구분 목록**(`FROM dbo.JINJU_SALES, dbo.Employee`)도 우회됐다 —
`finditer`가 `FROM` 뒤 첫 참조 하나만 잡고 콤마 뒤 항목은 보지 않았기 때문. 수식된 이름이어도 뚫렸다.

## 2. 수정 내용

### `backend/mcp_server/views_whitelist.py`

- `DEFAULT_SCHEMA = "dbo"` 상수 추가(+ 근거 주석). 화이트리스트 자체는 **무변경** —
  `SALES_VIEW_WHITELIST`는 여전히 `schema.view` 명시 나열이고, 새 뷰/별칭 추가 없음.

### `backend/mcp_server/sql_guard.py`

- `_TABLE_REF_PATTERN` **삭제**. 정규식 한 방 매칭 대신 3단 파서로 교체:
  - `_FROM_JOIN_PATTERN` — 모든 `FROM`/`JOIN` 키워드 위치를 찾는다.
  - `_CLAUSE_END_PATTERN` — 각 키워드 뒤에서 "테이블 참조 목록이 끝나는 지점"(`ON|WHERE|GROUP|ORDER|HAVING|UNION|EXCEPT|INTERSECT|INNER|LEFT|RIGHT|FULL|CROSS|OUTER|APPLY|JOIN|FROM|SELECT|PIVOT|UNPIVOT|OPTION|WITH|FOR|GO` 또는 `)`)까지를 잘라낸다.
  - 잘라낸 구간을 콤마로 분리 → 각 조각의 첫 토큰(`_REF_TOKEN_PATTERN`)이 테이블 참조.
    토큰이 없는 조각(`FROM (SELECT ...) t`의 파생 테이블)은 건너뛰고, 내부 `FROM`은 자기 매치에서 별도 검사된다.
- `_resolve_reference(token)` 추가:
  - 1부분(비수식) → `DEFAULT_SCHEMA` 보충 후 화이트리스트 대조 (MSSQL 기본 스키마 해석 반영)
  - 2부분 → 그대로 대조, 대괄호/따옴표 제거
  - 3부분 이상(교차 DB/링크드 서버) → **거부**
  - 빈 파트(`dbo..X`) → 거부
- `_check_and_qualify_table_refs(q)` 추가 — 검사 통과한 **비수식 참조를 `dbo.NAME`으로 실제 SQL에 다시 써 넣는다**.
  이로써 `MSSQL_READONLY_USER`의 기본 스키마가 `dbo`가 아니더라도, 우리가 "dbo로 해석될 것"이라 판단하고
  허용한 이름이 다른 스키마의 동명 객체로 해석되는 일이 없다. (db.py 전제조건에 대한 의존을 한 단계 줄임)
- `validate_and_prepare()`의 파이프라인 **순서는 그대로 유지**:
  다중문장 → SELECT-only → 금지 키워드 → 별칭 치환 → 테이블 참조 검사 → TOP 삽입.
  테이블 참조 검사 블록만 `q = _check_and_qualify_table_refs(q)` 한 줄로 교체.

### `backend/mcp_server/db.py`

- **변경 없음.** 다만 위 수식화 덕분에 "기본 스키마가 dbo"라는 암묵 전제에 대한 의존이 사라졌다.
  `MSSQL_READONLY_USER`가 화이트리스트 뷰에만 SELECT 권한을 갖는다는 운영 전제는 여전히 유효/필요.

## 3. 체인 정합성 검토 (sql-guardrail-review)

- [x] 화이트리스트는 `schema.view` 명시 나열 유지, 패턴 매칭/스키마 전체 허용으로 대체하지 않음
- [x] 신규 뷰/별칭 추가 없음 → 인사/급여/개인정보 노출 경로 신설 없음
- [x] 별칭 치환 → 키워드 검사 → 테이블 참조 검사 → 행수 제한 순서 유지
- [x] `rewrite_query_with_aliases()`와의 정합성: 한글 뷰 별칭은 `dbo.JINJU_SALES`(수식형)로 치환되므로
      새 검사에서 2부분 참조로 정상 통과. 별칭 치환이 놓친 토큰(`FROM 매출, 매출`의 두 번째 항목 등)은
      비수식 한글 이름 → `dbo.매출` → **거부**, 즉 실패 방향이 "덜 허용" 쪽이라 안전
- [x] 대괄호/대소문자 변형(`[dbo].[JINJU_SALES]`, `DBO.jinju_sales`) 정상 허용 확인
- [x] MCP 도구 스키마(`server.py`) 무변경 → Gemini FunctionDeclaration/시스템 프롬프트 영향 없음

## 4. 재현 사례 검증 (`validate_and_prepare()` 직접 호출)

| 쿼리 | 이전 | 현재 |
| --- | --- | --- |
| `SELECT * FROM dbo.JINJU_SALES UNION SELECT * FROM SecretTable` | ALLOWED | **BLOCKED** (`'dbo.SecretTable' 은(는) 허용된 매출 뷰 목록에 없습니다`) |
| `SELECT * FROM dbo.JINJU_SALES a JOIN SecretTable b ON 1=1` | ALLOWED | **BLOCKED** |
| `SELECT * FROM dbo.JINJU_SALES WHERE 1 IN (SELECT 1 FROM SecretTable)` | ALLOWED | **BLOCKED** |
| `SELECT * FROM dbo.JINJU_SALES, SecretTable` (신규 발견) | ALLOWED | **BLOCKED** |
| `SELECT * FROM dbo.JINJU_SALES, dbo.Employee` (신규 발견) | ALLOWED | **BLOCKED** |
| `SELECT * FROM otherdb.dbo.JINJU_SALES` (신규 발견) | ALLOWED | **BLOCKED** (3부분 이상) |
| `SELECT * FROM dbo.JINJU_SALES UNION SELECT * FROM @tv` / `#temp` | ALLOWED | **BLOCKED** |
| 대조군 `... UNION ALL SELECT a FROM sys.tables` | BLOCKED | BLOCKED (유지) |

## 5. 정상 쿼리 회귀 (오탐 없음)

| 쿼리 | 결과 |
| --- | --- |
| `SELECT SALES_AMT FROM dbo.JINJU_SALES` | ALLOW → `SELECT TOP 1000 ... FROM dbo.JINJU_SALES` |
| `SELECT SALES_AMT FROM [dbo].[JINJU_SALES]` | ALLOW |
| `SELECT SALES_AMT FROM JINJU_SALES` (비수식·화이트리스트) | ALLOW → `dbo.JINJU_SALES`로 수식되어 출력 |
| `FROM dbo.JINJU_SALES a JOIN dbo.JINJU_SALES b ON ...` (self join) | ALLOW |
| `SELECT * FROM (SELECT * FROM dbo.JINJU_SALES) t` (파생 테이블) | ALLOW |
| `SELECT * FROM dbo.JINJU_SALES WITH (NOLOCK)` | ALLOW |
| `SELECT 매출액 FROM 매출` (한글 별칭) | ALLOW → `SALES_AMT` / `dbo.JINJU_SALES` |
| `SELECT TOP 50 * FROM dbo.JINJU_SALES ORDER BY SALES_DT` | ALLOW (TOP 중복 없음) |
| `SELECT 1` | BLOCK (기존 동작 유지) |

## 6. 테스트

`backend/tests/test_sql_guard.py`에 `TestUnqualifiedTableReferences` 클래스 추가 (12 케이스):
재현 3건 파라미터화 + 콤마 목록(비수식/수식) + 단독 비수식 + `@tablevar`/`#temp` + 3부분 참조 +
비수식 화이트리스트 뷰 허용&수식화 + 파생 테이블 + `WITH (NOLOCK)`.

```
python -m pytest backend/tests -q
129 passed in 5.02s
```

기존 117개 전원 통과 + 신규 12개 통과. 회귀 없음.

## 7. 2차 수정 — qa-verifier 재검증 지적 반영 (F1~F4)

qa-verifier 독립 프로브에서 4건이 추가로 나와 **전부 수정**했다 (F4 포함).

### F1 (HIGH) — APPLY 우변이 검사되지 않음

`APPLY`는 구간 **종료** 키워드에만 있고 **시작** 키워드에는 없어서, T-SQL에서 FROM/JOIN과 동일한
table_source인 APPLY 우변이 통째로 화이트리스트 대조를 건너뛰었다.

- `_FROM_JOIN_PATTERN` → `_TABLE_SOURCE_PATTERN = \b(?:FROM|JOIN|APPLY)\b` 로 확장.
  `_CLAUSE_END_PATTERN`에는 그대로 남겨 선행 FROM 구간이 APPLY에서 끊기도록 유지.
- 결과: `CROSS APPLY HR.Payroll` / `dbo.Employee` / `SecretTable` / `dbo.SecretFn(...)` 전부 BLOCKED.
  TVF 호출은 토큰이 `dbo.SecretFn`으로 끊겨 화이트리스트 미등록으로 거부된다(이 프로젝트 정상 쿼리에 TVF 없음).
- `CROSS APPLY (SELECT 1 AS x) b`처럼 파생 테이블 우변은 정상 허용됨을 확인.

### F2 (MEDIUM) — 리터럴/주석 안의 FROM·JOIN 오탐

새 파서가 `FROM`/`JOIN` 단어만 보면 구간을 떠서, `WHERE CUST_NM = 'JOIN Corp'` 같은 정상 쿼리가
`'dbo.Corp'`로 오인되어 차단됐다(fail-closed지만 사용자에게는 원인 불명 차단).

- `_mask_non_code()` 추가: 문자열 리터럴(`'...'`, `''` 이스케이프), 한 줄 주석(`--`), 블록 주석(`/* */`)을
  **같은 길이의 공백으로** 치환한 사본을 만들고 그 위에서만 참조를 찾는다. 길이가 보존되므로
  수식화 치환은 원본 `q`에 그대로 적용된다.
- 마스킹 정규식은 **대괄호 식별자를 먼저 소비하고 보존**한다 — `[we'ird]` 처럼 식별자 안에 따옴표가
  들어가 리터럴 스캔이 어긋나면서 뒤쪽 실제 테이블 참조가 숨겨지는 우회를 막기 위함.
- 금지 키워드 검사는 **마스킹하지 않은 원문**에 그대로 수행한다(기존 회귀 테스트
  `test_forbidden_keyword_inside_string_literal_is_still_blocked`의 "덜 허용" 동작 유지).
- 부수 효과: `FROM /*x*/ SecretTable`이 이제 `dbo./*x*/SecretTable`이라는 이상한 이름이 아니라
  `dbo.SecretTable`로 제대로 된 사유로 거부된다.

### F3 (MEDIUM) — `SELECT ... INTO` 통과

`INTO`를 `_FORBIDDEN_KEYWORDS`에 추가. `SELECT * INTO SecretCopy FROM dbo.JINJU_SALES` → BLOCKED.
모듈 최상단 "DDL/DML 금지" 원칙이 이제 코드로 강제된다.
`backend/app/config.py` 시스템 프롬프트에 `INTO` 사용 지시가 없음을 확인했으므로 정상 흐름 영향 없음.

### F4 (LOW) — 대괄호 안에 점이 든 단일 식별자

`[dbo.JINJU_SALES]`가 `token.split(".")` 때문에 2부분 수식 참조로 오인됐다.

- `_split_identifier_parts()` 추가 — 대괄호/따옴표(`]]`, `""` 이스케이프 포함) 안의 점은 구분자로 보지 않는다.
- 분해 결과의 어떤 파트에라도 점이 남으면 "해석할 수 없는 테이블 참조"로 거부.

### 2차 수정 후 검증

- 프로브 30종(차단 15 / 허용 15) 전부 기대대로: **failures 0**
- `python -m pytest backend/tests -q` → **144 passed** (117 기존 + 27 신규)
- 신규 테스트 클래스: `TestApplyOperator`(6), `TestLiteralAndCommentMasking`(7), `TestSelectInto`(1),
  `TestUnqualifiedTableReferences`에 대괄호-점 케이스 1건 추가

## 8. 후속 권고

- qa-verifier: 새 가드 규칙(비수식 참조 수식화, 콤마 목록 검사, 3부분 참조 거부)에 대해
  독립적인 우회 시나리오 재검증 권장.
- 운영: `MSSQL_READONLY_USER`의 권한을 화이트리스트 뷰로 한정하는 전제는 코드가 강제하지 않는
  3단째 방어이므로 DB 측 GRANT 점검이 여전히 필요하다.
