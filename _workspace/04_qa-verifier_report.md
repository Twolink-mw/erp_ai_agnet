# QA 리포트 — Gemini 도구 미호출 환각 방지(그라운딩 체크)

결론: **통과** (차단성 회귀 없음). 단, 설계상 오탐 경로 1건은 사용자 확인 필요 — 아래 [관찰 1].

이전 작업(이메일 프리셋) 리포트는 `_workspace/04_qa-verifier_report_email-preset.md`로 보존.

## 1. 테스트 스위트
- pytest (`backend/tests`, 루트 pytest.ini, asyncio_mode=auto): **184/184 통과** (5.08s, 실패 0)
  - 이전 176건 + 신규 `test_gemini_agent_loop.py` 그라운딩 관련 8건 = 184. 보고된 수치 재확인 완료.
- vitest (`frontend`, `npx vitest run`): **48/48 통과** (2 파일, 5.74s, 실패 0)
  - Chat.test.tsx 33 / ChartRenderer.test.tsx 15. act(...) 경고는 기존부터 있던 것으로 실패 아님.

## 2. PDF/이메일 재사용 플로우 충돌 여부 — 통과
`gemini_agent.py:124-127`
```python
history_already_grounded = any(
    m.get("role") == "assistant" and has_reportable_content(m.get("content") or "")
    for m in messages
)
```
- 판정 조건(`gemini_agent.py:155`)은 `looks_like_data and not ran_run_sql_this_turn and not history_already_grounded`
  — 이전 assistant 메시지에 표/차트가 있으면 그라운딩 체크 자체를 건너뛴다. 의도대로 동작.
- 프론트가 히스토리를 온전히 보내는지 교차 확인: `Chat.tsx:528`이 `body: JSON.stringify({ messages: next })`로
  assistant `content` 원문(표 + ```chart 블록 포함)을 그대로 전송한다. 따라서 "PDF로 만들어줘" 턴에서
  `history_already_grounded=True`가 성립한다.
- `Chat.tsx`가 함께 보내는 `reportAvailable` 여분 필드는 `main.py:50` `ChatMessage`(role/content)의
  pydantic 기본 동작상 무시되므로 422 없음.
- 회귀 테스트 존재: `test_history_with_prior_reportable_content_skips_grounding_check`
  (generate_content 1회만 호출, tool_calls 비어있음 검증).

## 3. 재시도 루프 / 타임아웃 — 통과
- 그라운딩 재시도는 `for _ in range(MAX_TOOL_ROUNDS)` 안에서 `continue`로 처리된다(`gemini_agent.py:174`).
  **별도 루프 없음** → generate_content 호출 상한은 여전히 10회. 예산 공유 확인.
- `MAX_GROUNDING_RETRIES=2` 소진 시 `_UNGROUNDED_FALLBACK_REPLY` 즉시 반환(`:180-183`) → 무한루프 불가.
- `test_grounding_retry_does_not_break_max_tool_rounds_fallback`이 이 상호작용을 커버.

## 4. 반환 계약 / API 스키마 — 통과
- `run_chat()`의 모든 종료 경로(정상 / 그라운딩 폴백 / MCP 연결 실패 / 라운드 초과)가
  `{"reply": str, "tool_calls": list}`를 반환. 신규 폴백 경로도 `tool_calls_log`를 함께 반환.
- `main.py:69` `result.setdefault("report_available", has_reportable_content(reply))` →
  그라운딩 폴백 텍스트에는 표/차트가 없으므로 `report_available=False`. PDF/이메일 버튼이
  잘못 노출되지 않는다.
- 프론트 `Chat.tsx:537` `data?.report_available ?? false` 방어적 파싱 유지 — 계약 무변경.

## 5. 라이브 스모크 (실행됨)
포트 8000에 uvicorn이 떠 있어 실제 `/api/chat` 1건 실행.
- 요청: "매출 뷰에서 최근 매출 상위 3건만 간단히 보여줘"
- 결과: 200, `tool_calls`에 `list_sales_views` → `get_view_aliases` → `get_view_schema` → `run_sql` 기록,
  응답에 마크다운 표 + `chart` 블록(type/title/xKey/series/data) 정상 포함. 그라운딩 폴백 미발동.
- 로그 파일 확인은 **환경상 미검증**: `backend/uvicorn.err.log`가 이 요청을 포함하지 않는다
  (마지막 기록 08-21 00:36, 액세스 로그도 없음 → 현재 실행 중인 프로세스의 stderr가 이 파일로
  리다이렉트되어 있지 않음). 대신 in-process로 `backend.app.main` import 후 root 로거가
  level=INFO + StreamHandler(stderr)로 설정되고 `backend.app.gemini_agent` 로거가
  `tool_call: name=...`을 stderr로 실제 출력함을 확인. 테스트도 `caplog`로 커버
  (`test_tool_call_is_logged_at_info`, `test_grounding_retry_emits_warning_log`). 실패 아님.

## 6. 경계면 정합성 (스킬 체크리스트)
- [통과] 화이트리스트 ↔ SQL 가드: `SALES_VIEW_WHITELIST`(dbo.JINJU_SALES) 전 항목이 수식/비수식 모두 통과.
  우회 시도 전량 차단 확인 — 다중 문장(`; DROP TABLE`), `; EXEC sp_executesql`,
  비화이트리스트 `[dbo].[NotAllowedView]`, `CROSS APPLY dbo.Bad`, 대소문자 변형
  `SeLeCt ... uNiOn all select * from dbo.Secret`, `SELECT ... INTO`. `SELECT DISTINCT TOP 5`는 정상 허용.
- [통과] MCP 도구 ↔ Gemini FunctionDeclaration: `_mcp_tools_as_gemini_tool()`이 `list_tools()` 결과를
  그대로 변환(하드코딩 없음). 라이브 호출에서 도구 4종 실제 사용 확인.
- [통과] chart 스키마: `config.py:71-73`의 `{type,title,xKey,series[{key,name}],data}`와
  `ChartRenderer.tsx:19-24 / 61-64`의 `parseChartSpec` 검증 필드가 일치.
- [통과] 환경변수 전달: `mcp_client.py:35` `env=dict(os.environ)`로 MSSQL_*/GEMINI_* 상속.

## 7. 가드 파일 변경 여부 — 통과
`git diff -- backend/mcp_server/`의 변경분은 전부 **이전 세션의 가드 강화 작업**
(TOP/DISTINCT 순서 처리, `INTO` 금지 키워드 추가, 테이블 참조 추출 정규식 개선)이며,
이번 그라운딩 변경과는 무관하다. 이번 diff가 이 파일들을 추가로 건드린 흔적 없음.
관련 `test_sql_guard.py`도 전량 통과.

## 관찰 사항 (차단성 아님)

### [관찰 1] 도구는 호출했지만 run_sql은 아닌 정상 응답이 폴백으로 버려질 수 있음
`gemini_agent.py:152`
```python
ran_run_sql_this_turn = any(c["name"] == "run_sql" for c in tool_calls_log)
```
그라운딩 판정이 **run_sql 호출 여부만** 본다. 그런데 `has_reportable_content()`는
마크다운 표만 있어도 True다(직접 확인: 컬럼 목록 표 → True).

재현 시나리오: 사용자가 "매출 뷰에 어떤 컬럼들이 있어?"라고 물으면 모델은
`get_view_schema` / `get_view_aliases`만 호출하고 컬럼 목록을 **표로** 정리해 답한다.
이때 `looks_like_data=True`, `ran_run_sql_this_turn=False`, `history_already_grounded=False`
→ 불필요한 재시도 2회 후 `_UNGROUNDED_FALLBACK_REPLY`("실제 데이터를 조회해 확인하지 못했습니다")로
정상 답변이 폐기된다. 라운드 예산도 3회 소모.

수정 제안(택1):
- (a) `ran_run_sql_this_turn` → `bool(tool_calls_log)` 로 완화 (도구를 하나라도 호출했으면 그라운딩된 것으로 간주)
- (b) 데이터 조회성 도구 집합으로 판정:
  `any(c["name"] in {"run_sql", "get_view_schema"} for c in tool_calls_log)`
- (c) 현행 유지가 의도라면(수치 환각 차단을 최우선) 그대로 두되, 시스템 프롬프트에
  "스키마/뷰 목록 안내는 표 대신 목록으로 답한다" 지시를 추가해 오탐 표면을 줄인다.

(a)가 환각 방지 목적을 유지하면서 오탐을 없애는 가장 단순한 안이다 — 도구를 전혀 호출하지 않은
경우가 원래 방어 대상이었기 때문이다.

### [관찰 2] 로그 리다이렉트 파일이 현재 실행 중인 서버와 연결돼 있지 않음
`backend/uvicorn.err.log`에 최신 요청 로그가 전혀 남지 않는다(액세스 로그 포함).
운영 확인 시 콘솔을 직접 보거나 uvicorn을 `2> backend/uvicorn.err.log`로 재기동해야 한다.
코드 결함 아님.
