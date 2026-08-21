---
name: gemini-agent-dev
description: "Gemini 함수 호출 루프(backend/app/gemini_agent.py), MCP 클라이언트 세션 관리(mcp_client.py), 시스템 프롬프트(config.py) 작업 절차. run_chat() 수정, MAX_TOOL_ROUNDS 조정, 새 MCP 도구를 Gemini FunctionDeclaration으로 노출, 시스템 프롬프트에 새 지시 추가 요청 시 사용."
---

# Gemini Agent Dev

`run_chat()`은 MCP 도구를 Gemini 함수 호출로 노출하고, 결과를 대화 형태로 조립하는 핵심 루프다.
이 루프의 두 가지 불변 조건(세션 1턴 1개, 시스템 프롬프트의 별칭 해석 지시)을 지키지 않으면
동시 요청 성능 저하 또는 SQL 오류가 조용히 재발한다.

## 루프 구조

```
1. McpSalesClient 새로 열기 (이 요청 전용)
2. MCP 서버의 도구 5개를 Gemini FunctionDeclaration으로 변환
3. loop (최대 MAX_TOOL_ROUNDS = 10회, temperature=GEMINI_TEMPERATURE=0.2):
   a. generate_content(history + tools) 호출
   b. 응답이 function_call이면: MCP 세션에 위임해 실행 → 결과를 function_response로 history에 추가
      (tool_call 이름/인자/출력 일부를 logger.info로 기록)
   c. 응답이 텍스트만이면: 그라운딩 체크(아래) 통과 시 루프 종료·반환, 실패 시 correction
      메시지를 주입하고 같은 루프의 다음 반복으로 재시도(MAX_GROUNDING_RETRIES 예산 내)
4. finally: McpSalesClient 닫기
```

## 그라운딩 체크 (도구 미호출 환각 / 코드 덤프 방지)

`function_call` 없이 텍스트 응답이 나왔을 때, 그 응답을 무조건 신뢰하지 않고 두 가지를 확인한다:

1. **미검증 데이터 환각**: 응답이 표/차트(`has_reportable_content()`, `pdf_report.py`에서 재사용)를
   담고 있는데 이번 턴에 도구가 하나도 호출되지 않았고, 대화 이력에도 이미 그라운딩된(표/차트가
   있는) assistant 메시지가 없으면 — 도구 호출 없이 데이터를 지어낸 것으로 간주한다. (이력 체크는
   "PDF/이메일로 만들어줘" 같은 직전 결과 재사용 플로우를 오탐하지 않기 위함이다.)
2. **코드 덤프**: 응답에 ` ```chart ` 이외의 코드 펜스(` ```python `, ` ```sql `, 언어 태그 없는
   ` ``` ` 등)가 있으면 — 도구 호출 여부와 무관하게 형식 위반으로 간주한다(코드 실행 도구가 없어
   실행 안 된 텍스트만 노출되기 때문).

둘 중 하나라도 해당하면 `MAX_GROUNDING_RETRIES`(2) 예산 안에서 correction 메시지를 주입해 재시도한다
(같은 `for` 루프를 `continue`— 별도 루프를 만들어 `MAX_TOOL_ROUNDS` 예산을 우회하지 않는다, 타임아웃
이중 위험 방지). 예산 소진 시 실제 없는 데이터를 노출하지 않기 위해 안전한 폴백 문구를 반환한다.
새 그라운딩 판정 규칙을 추가할 때도 이 "재시도 예산 공유" 원칙을 유지한다.

## 세션을 요청마다 새로 여닫는 이유 (건드리지 말 것)

MCP 세션은 stdio 서브프로세스와 파이프로 통신한다. 세션을 앱 전체에서 공유하면, 동시에 들어온 채팅 요청들이
같은 파이프를 두고 경합해 서로의 도구 호출을 직렬화시킨다 — 즉 동시성이 사라지고 한 사용자의 느린 쿼리가
다른 사용자를 블로킹한다. 요청 1턴마다 새 프로세스를 열고 닫는 비용은 이 직렬화 문제보다 작다고 판단된 의도적 설계다.
"최적화"를 위해 세션 풀링/공유로 바꾸기 전에 이 트레이드오프를 사용자와 재확인한다.

## 새 MCP 도구를 추가했을 때 (mcp-guardian이 server.py에 도구 추가)

1. 도구 목록 → `FunctionDeclaration` 변환 로직이 새 도구를 자동으로 포함하는지 확인 (하드코딩된 도구 목록이면 수동 추가 필요)
2. `SYSTEM_PROMPT`가 새 도구를 언제 어떻게 쓰는지 지시해야 하는지 판단 (예: 새 집계 도구라면 "이런 요청에는 이 도구를 우선 사용하라" 지시 추가)
3. `backend/tests/test_gemini_schema_convert.py`로 변환 결과 검증

## 환경변수 전달 (mcp_client.py)

MCP SDK의 기본 서브프로세스 환경은 OS 화이트리스트만 상속하므로, `MSSQL_*`/`GEMINI_*`가 자식 프로세스에 전달되지 않는다.
`mcp_client.py`는 부모 프로세스의 전체 환경변수(`os.environ`)를 명시적으로 서브프로세스 시작 인자에 전달해야 한다.
이 부분을 수정할 때는 전달되는 환경변수 목록이 축소되지 않았는지 확인한다 — 축소되면 MCP 서버가 조용히
DB 연결에 실패하거나 Gemini 키를 못 찾는 형태로 나타난다.

## SYSTEM_PROMPT 수정 시 유지해야 할 지시

1. SQL 작성 전 `get_view_aliases`/`get_column_aliases`로 한글 별칭을 실제 이름으로 해석하라는 지시
2. 추이/비교 분석 결과에는 ` ```chart ` JSON 블록을 함께 출력하라는 지시 (프론트 `ChartRenderer.tsx`가 이 태그로 코드 블록을 가로챈다)
3. 도구(run_sql)로 실제 조회하기 전에는 수치/표/차트를 지어내지 말라는 지시 — 위 그라운딩 체크와
   짝을 이루는 방어층이다(프롬프트 지시만으로는 강제되지 않으므로 코드 체크가 필수다)
4. 코드 블록(```python 등)을 최종 답변에 포함하지 말라는 지시 — 마찬가지로 코드 덤프 감지와 짝을 이룬다
5. "이번달/지난달 대비 순위 변동" 질문용 검증된 SQL 템플릿(사용자 실사용 쿼리를 CTE 없는
   서브쿼리+LEFT JOIN 구조로 반영, DIFF_RANK의 ▲/▼ 부호 규칙 포함) — 탐색적 재시도로 인한
   타임아웃을 막기 위한 few-shot 힌트다. 부호 규칙을 임의로 "고치지" 않는다.

이 지시들을 삭제하거나 애매하게 바꾸면 Gemini가 잘못된 컬럼명으로 SQL을 생성하거나, 프론트에서
차트가 렌더링되지 않거나, 그라운딩 체크/코드 덤프 감지가 막던 문제가 재발한다.
chart 블록의 JSON 스키마를 바꾸려면 frontend-dev에게 반드시 먼저 알린다.

## MAX_TOOL_ROUNDS / MAX_GROUNDING_RETRIES 조정 시 고려사항

늘리면: 복잡한 다단계 분석(예: 여러 뷰를 순차 조회 후 비교)이 가능해지지만, 응답 지연이 커진다.
`next.config.js`의 `proxyTimeout: 240_000`(240초) 안에 끝나야 하므로, 라운드 수와 평균 도구 실행
시간(Gemini API 응답이 드물게 100초 이상 걸리는 지연 스파이크가 실측된 바 있음을 감안)을 곱해
여유가 있는지 확인한다. 그라운딩 재시도는 `MAX_TOOL_ROUNDS` 예산을 공유하므로 별도로 늘어나지 않는다.
줄이면: 응답은 빨라지지만 복잡한 요청에서 Gemini가 끝맺지 못하고 중간 결과를 반환할 수 있다.

## 검증
- `backend/tests/test_chat_api.py`, `test_gemini_agent_loop.py`, `test_gemini_schema_convert.py`, `test_mcp_client_env.py` 실행
- 수동 점검: `python -m backend.scripts.test_mcp_client` (venv 활성화 후, `.env` 필요)
- 로컬 서버 기동 후 매출 질문 1건을 보내 `backend/uvicorn.err.log`(또는 콘솔)에 `tool_call: name=...`
  로그가 남는지, 그라운딩 재시도가 필요 이상으로 발동하지 않는지 육안 확인
