# QA 리포트 — 코드 덤프 방지 기능 (2026-08-21)

**결론: 통과** (기능 결함 없음. 경화 권고 2건, 설계 판단 재확인 1건은 아래 참고 항목)

## 테스트 스위트
- pytest (`backend/tests`, 루트 `pytest.ini`, asyncio_mode=auto): **201 passed / 201**, 4.75s. 실패 없음.
- vitest (`frontend`, `npx vitest run`): **48 passed / 48** (2 files). 실패 없음.
  - `act(...)` 경고는 기존부터 있던 것으로 실패 아님.
- 수동 점검 스크립트(`backend/scripts/test_*.py`)는 실제 DB/Gemini 연결이 필요해 **미실행**(정책대로 스킵).

## `_contains_non_chart_code_block()` 직접 재검증

`backend/app/gemini_agent.py:35-53`. 테스트 스위트와 별개로, 함수를 직접 import해 18케이스를 실행했다.

| 케이스 | 기대 | 실제 |
|---|---|---|
| ` ```chart\n{...}\n``` ` (정상 차트) | False | **False** ✅ 회귀 없음 |
| ` ```python\nprint(1)\n``` ` | True | True |
| ` ```sql\nSELECT 1\n``` ` | True | True |
| 언어 태그 없는 ` ```\n...\n``` ` | True | True |
| 마크다운 표만 (펜스 없음) | False | False |
| 인라인 백틱 `` `code` `` | False | False |
| chart 블록 + 뒤이은 python 블록 | True | True |
| ` ```CHART ` (대문자) | False | False |
| ` ```chart   ` (뒤 공백) | False | False |
| 들여쓴 ` ```chart ` | False | False |
| chart 블록 2개 연속 | False | False |
| 닫히지 않은 ```python | True | True |
| 닫히지 않은 ```chart | False | False |
| chart 블록 뒤 언어없는 펜스 | True | True |
| 빈 문자열 | False | False |
| ` ```chartjs ` | True | True |
| ` ~~~python ` (틸드 펜스) | (하드닝) | False — 미탐지 |
| ` ````python ` (백틱 4개) | (하드닝) | False — 미탐지 |

**핵심 회귀 포인트인 "정상 ```chart 블록 오탐"은 완전히 해소됐다.** 이전 `(?!chart\b)` 정규식이 닫는
펜스(언어 태그 없음)를 오탐하던 버그는, 펜스를 열림/닫힘으로 토글하며 **여는 펜스의 언어 태그만** 검사하는
방식으로 근본 해결됐다.

## 재시도 예산 / 루프 안전성

`gemini_agent.py:209-255`.
- `is_ungrounded`와 `is_code_dump`가 **동일한 `grounding_retries` 카운터**를 공유한다 (사유별 별도 카운터
  아님). 한 턴에 둘 다 참이면 correction 메시지 2개를 `"\n".join`으로 합쳐 1회만 소비한다 — 이중 차감 없음.
- 재시도는 `continue`이므로 `for _ in range(MAX_TOOL_ROUNDS)` 이터레이션을 소비한다. 즉 총
  `generate_content` 호출 수는 `MAX_TOOL_ROUNDS(10)`로 상한이 걸리며, 재시도가 라운드 예산을 우회해
  추가 호출을 만들지 않는다. **무한루프/추가 타임아웃 위험 없음.**
- 예산 소진 시 `_UNGROUNDED_FALLBACK_REPLY`(ungrounded 우선) 또는 `_CODE_DUMP_FALLBACK_REPLY` 반환.
- 회귀 테스트 `test_grounding_retry_does_not_break_max_tool_rounds_fallback`이 이 경계를 커버.

## 기존 그라운딩 체크 회귀 (get_view_schema만 호출 + 표 응답)

깨지지 않았다. `is_ungrounded`는 `not any_tool_called_this_turn`을 요구하므로 어떤 도구든 호출됐으면 False.
`is_code_dump`는 도구 호출과 무관하지만 순수 마크다운 표에는 펜스가 없어 False. 두 판정이 독립적으로
동작하며 서로 오탐을 유발하지 않음을 코드와 실측 양쪽으로 확인
(`test_non_run_sql_tool_call_with_table_reply_is_not_retried` 통과).

## 경계면 검증

- **[통과]** `run_chat()` 반환 계약: 정상/재시도소진/라운드초과 **모든 경로가 `{"reply": str,
  "tool_calls": list}`** 동일 형태. 신규 키 추가 없음.
- **[통과]** `/api/chat` 스키마 (`main.py:67-71`): `ChatResponse(reply, tool_calls, report_available)`.
  `report_available`은 `setdefault`로 `has_reportable_content(reply)`에서 계산되므로, 코드덤프 폴백
  응답(표/차트 없음)에서는 자연히 `False`가 되어 PDF/이메일 버튼이 노출되지 않는다 — 일관됨.
- **[통과]** chart 스키마 (백엔드 ↔ 프론트): `SYSTEM_PROMPT`(config.py:76-80)의
  `type / title / xKey / series[{key,name}] / data[]`와 `ChartRenderer.parseChartSpec`
  (ChartRenderer.tsx:56-72)이 요구하는 `type ∈ {bar,line}` + `xKey:string` + `series:Array` +
  `data:Array` 가 정확히 일치. `Chat.tsx:598`의 `/language-chart/` 매칭도 ` ```chart ` 소문자 태그와 일치.
- **[통과]** MCP 도구 ↔ Gemini FunctionDeclaration: `_mcp_tools_as_gemini_tool()`이
  `mcp_client.list_tools()` 결과를 **동적 변환**(하드코딩 없음)하므로 도구 드리프트 구조적으로 불가.
- **[통과]** 변경 범위: mtime 기준 이번 세션(2026-08-21 00:55~00:56) 수정 파일은
  `backend/app/config.py`, `backend/app/gemini_agent.py`, `backend/tests/test_gemini_agent_loop.py`
  **3개뿐**. `backend/mcp_server/*`는 08-20 이후 무변경(sql_guard.py/views_whitelist.py의 diff는 이전
  세션 산출물). **범위 밖 파일 오염 없음.**

## 참고 항목 (블로커 아님)

1. **[하드닝] 틸드 펜스 / 4-백틱 펜스 미탐지** — `gemini_agent.py:33`
   `_FENCE_LINE_RE = ^[ \t]*```[ \t]*([A-Za-z0-9_+#.-]*)[ \t]*$`
   `~~~python` 과 ` ````python `(백틱 4개)은 CommonMark 유효 코드 펜스이고 react-markdown이 실제
   코드 블록으로 렌더링하지만 이 정규식은 잡지 못한다. Gemini가 이 형태를 내는 빈도는 낮으므로 현 상태로도
   실사용 방어는 성립. 강화하려면 `` ```{3,} `` 와 `~{3,}`를 함께 인식하도록 확장 (단, 확장 시
   `pdf_report._FENCE_RE`도 같은 규칙으로 맞춰야 두 파서의 계약이 어긋나지 않는다).
2. **[정합성 나이트] 펜스 정규식 문자클래스 불일치** — `gemini_agent.py:33`은 `[A-Za-z0-9_+#.-]`,
   `pdf_report.py:120`은 `[A-Za-z0-9_-]`. 주석은 "같은 계약"이라고 명시하지만 실제로는 다르다. 방향이
   안전한 쪽(감지가 더 넓음)이라 무해하나, 주석 문구를 정확히 하거나 상수를 공유하면 향후 혼선을 줄인다.
3. **[설계 판단 재확인] 그라운딩된 답변까지 통째로 폐기** — `gemini_agent.py:249-255`
   도구를 정상 호출해 실제 데이터로 표를 만든 답변이라도, 부수적으로 ` ```sql ` 블록 하나가 섞여 있고
   재시도 2회로 고쳐지지 않으면 답변 전체가 `_CODE_DUMP_FALLBACK_REPLY`("죄송합니다...")로 대체된다.
   근거 없는 수치와 달리 코드 덤프는 "형식 위반"이므로, 펜스만 제거하고 나머지를 살리는 편이
   사용자 가치가 클 수 있다. 의도된 동작이면 그대로 두어도 무방(보안/정확성 위험은 없음).
