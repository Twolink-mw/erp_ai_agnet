---
name: erp-integration-qa
description: "이 프로젝트(사내 ERP 매출 챗봇)의 pytest/vitest 스위트 실행과 mcp_server↔app↔frontend 경계면 정합성 검증 절차. 코드 변경 후 회귀 확인, '테스트 돌려줘', '검증해줘', 새 뷰/도구/chart 스키마 추가 후 점검 요청 시 사용."
---

# ERP Integration QA

이 프로젝트는 두 종류의 경계면을 가진다: (1) SQL 접근 통제 3단 체인, (2) MCP 서버 → Gemini 에이전트 → 프론트엔드
3계층. 각 계층은 개별적으로 테스트를 통과해도 경계에서 어긋날 수 있다 — 존재 확인이 아니라 **양쪽을 동시에 읽는 교차 비교**가 필요하다.

## 테스트 실행

```bash
# 백엔드 (venv 활성화 후, 루트에서)
pytest

# 프론트엔드
cd frontend
npm test
```

`backend/scripts/test_db_connection.py`, `test_mcp_client.py`, `test_chat_err.py`는 실제 DB/Gemini API 연결이
필요한 수동 점검 스크립트다 (`.env` 필요). 자동 스위트가 아니므로, 실행 전 `.env` 존재를 확인하고 실행 여부를
사용자에게 확인한다 — CI나 자동화된 컨텍스트에서 임의로 실행하지 않는다.

## 경계면별 교차 비교 방법

### 1. 화이트리스트 ↔ SQL 가드 ↔ DB 권한

`backend/mcp_server/views_whitelist.py`의 `SALES_VIEW_WHITELIST`와 `sql_guard.py`의 테이블 참조 검사 로직을
동시에 열어, 화이트리스트의 모든 항목이 실제로 검사를 통과하는 형식(대소문자, 대괄호 표기)으로 되어 있는지 확인한다.
그 다음 우회 시나리오를 직접 실행해본다:

```
예시 우회 시도 (모두 차단되어야 함):
- SELECT * FROM 화이트리스트뷰; DROP TABLE x
- SELECT * FROM [dbo].[비화이트리스트뷰]
- SELECT * FROM 화이트리스트뷰 WHERE 1=1; EXEC sp_executesql N'...'
- WITH cte AS (SELECT * FROM 비화이트리스트뷰) SELECT * FROM cte
```

주의: CTE(`WITH ... AS (...) SELECT ...`) 자체는 이제 정식 지원되는 문법이다(월별 순위
변동처럼 다단계 집계가 필요한 질문에서 흔히 쓰임). 위 마지막 예시가 차단돼야 하는 이유는
"WITH로 시작해서"가 아니라 **CTE 본문 안에 화이트리스트 밖 테이블(`비화이트리스트뷰`)이
숨어있어서**다 — 같은 구조라도 화이트리스트 뷰만 참조하면 정상 통과해야 한다. 회귀 확인 시
`WITH cte AS (SELECT * FROM 화이트리스트뷰) SELECT * FROM cte`(정상 통과)와
`WITH cte AS (SELECT * FROM 비화이트리스트뷰) SELECT * FROM cte`(차단)를 함께 테스트해서
둘의 결과가 반대인지 확인한다.

### 2. MCP 도구 ↔ Gemini FunctionDeclaration

`backend/mcp_server/server.py`가 노출하는 도구 5개의 이름·파라미터와 `gemini_agent.py`가 변환한
`FunctionDeclaration` 목록을 나란히 대조한다. 새 도구가 추가됐는데 변환 로직이 하드코딩되어 있으면 새 도구가 Gemini에게
보이지 않는 채로 조용히 무시될 수 있다.

### 3. 시스템 프롬프트의 chart 스키마 ↔ ChartRenderer의 parseChartSpec

`backend/app/config.py`의 `SYSTEM_PROMPT`가 지시하는 chart JSON 구조(필드명, 타입)와
`frontend/components/ChartRenderer.tsx`의 `parseChartSpec`이 기대하는 필드를 나란히 읽고 비교한다.
필드명 하나만 달라도(`data` vs `series` 등) 파싱 실패로 이어진다.

### 4. 환경변수 전달

`mcp_client.py`가 서브프로세스 실행 시 전달하는 환경변수 목록에 `MSSQL_*`, `GEMINI_*`가 실제로 포함되는지
코드를 읽고 확인한다 (MCP SDK 기본값은 OS 화이트리스트만 상속하므로 명시적 전달이 없으면 누락된다).

## 점진적 검증 원칙

각 담당 에이전트(mcp-guardian/backend-dev/frontend-dev)의 작업이 끝날 때마다 해당 영역만 즉시 검증한다.
전체 기능이 완성된 후 한 번에 검증하면 초기 경계면 불일치가 후속 작업에 전파되어 수정 비용이 커진다.

## 리포트 형식

```markdown
## QA 리포트

### 테스트 스위트
- pytest: {통과}/{전체} (실패 목록)
- vitest: {통과}/{전체} (실패 목록)

### 경계면 검증
- [통과/실패/미검증] 화이트리스트 ↔ SQL 가드: {비고}
- [통과/실패/미검증] MCP 도구 ↔ Gemini 스키마: {비고}
- [통과/실패/미검증] chart 스키마 (백엔드 ↔ 프론트): {비고}
- [통과/실패/미검증] 환경변수 전달: {비고}

### 발견된 문제 (파일:라인 + 재현 방법 + 수정 제안)
1. ...
```
