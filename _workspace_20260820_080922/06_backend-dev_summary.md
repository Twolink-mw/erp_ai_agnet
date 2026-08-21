# 06 backend-dev — "도구 호출 횟수를 초과했습니다" 오류 개선

담당: backend-dev / 범위: `backend/app/config.py`, `backend/app/gemini_agent.py` (2개 파일만)
`backend/mcp_server/**`(도구 스키마, 화이트리스트, sql_guard, db)는 일절 수정하지 않음.

## 1. 변경 내용

### (1) `backend/app/config.py` — SYSTEM_PROMPT에 MSSQL 방언 지시 추가

별칭 해석 지시 바로 앞에 다음 항목을 추가:

```
- 대상 DB는 Microsoft SQL Server(MSSQL)다. 결과 개수를 제한할 때는 `LIMIT`이 아니라
  `SELECT TOP N ...`을 사용한다 (MSSQL에는 LIMIT 구문이 없어 오류가 난다).
  마찬가지로 페이징이 필요하면 `OFFSET ... FETCH NEXT ... ROWS ONLY`를 사용한다.
```

- 근거: `_workspace/05_qa-verifier_final_report.md` 잔여 관찰 사항 #2 — 실기동 2회 모두
  Gemini가 1차 시도에서 `LIMIT 5`를 생성해 거부당하고 스스로 `TOP 5`로 재시도, 라운드 1회와
  수 초를 낭비. 다단계 질문과 겹치면 라운드 소진을 앞당긴다.
- 기존 두 불변 지시(별칭 해석 `get_view_aliases`/`get_column_aliases`, ` ```chart ` JSON 블록)는
  그대로 유지. chart 블록 스키마 변경 없음 → **frontend-dev에 통보할 파싱 계약 변경 없음.**

### (2) `backend/app/gemini_agent.py` — `MAX_TOOL_ROUNDS` 6 → 10

근거 주석을 상수 위에 함께 남김:

- 정당한 다단계 질문의 실제 소요 라운드: 뷰 목록(1) + 스키마(1) + 컬럼 별칭(1) + 조회 N회(2~4)
  + 최종 텍스트 라운드(1) ≈ 6~8. 6은 마진이 없어 정상 질문이 폴백 메시지에 걸렸다.
- 상한 근거: 프론트 `next.config.js`의 `proxyTimeout: 120_000`(120초) 안에 끝나야 한다.
  실측 라운드당 약 3~8초(Gemini 호출 + SQL 실행)를 가정하면 10라운드 최악 ~80초로,
  타임아웃 이전에 폴백 메시지를 반환할 여유가 남는다. 12 이상은 최악 케이스가 120초를
  넘겨 프론트에서 프록시 타임아웃(사용자에게 아무 메시지도 못 감)이 되므로 채택하지 않음.

### (3) 두 변경의 상충 여부

상충 없음, 오히려 상호 보완적이다. (1)이 LIMIT→TOP 재시도 왕복을 제거해 **필요 라운드 수 자체를
1 줄이고**, (2)는 남은 정상 다단계 경로에 마진을 준다. 즉 (2)의 상향은 (1) 적용 후 기준으로도
과하지 않으며, 평균 응답 시간은 (1) 때문에 오히려 짧아진다(늘어난 상한은 실패 경로에서만 소비).

### (4) MCP 세션 구조 영향 확인 — 영향 없음

`run_chat()`은 요청 진입 시 `McpSalesClient()`를 1개 열고 `finally`에서 닫으며, 라운드 루프는
그 **단일 세션 안의 반복**이다. 라운드 수 변경은 세션 개수/수명에 영향을 주지 않는다.
`mcp_client.py`의 요청당 세션 개폐 설계와 `env=dict(os.environ)` 전체 환경변수 전달 로직은 무수정.

## 2. pytest 결과 (회귀 없음)

```
d:\WebDev\AI_Agent\backend> .venv\Scripts\python.exe -m pytest tests -q
144 passed in 4.55s
```

기존 144개 전부 통과. `test_gemini_agent_loop.py:115`의 폴백 테스트는
`gemini_agent.MAX_TOOL_ROUNDS` 상수를 참조하므로 값 변경에 자동 추종(하드코딩 6 없음).

## 3. 실기동 확인

워크스페이스 루트에서 재기동 (기존 프로세스는 `--reload`가 아니어서 종료 후 재시작):
`backend\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --port 8000`

질의: "최근 월별 매출 추이와, 매출 상위 3개 제품을 함께 알려줘. 추이는 차트로도 보여줘."

결과: `HTTP 200`, 소요 **36.6초**, 도구 호출 **5회**(상한 10에 여유), 정상 답변 반환.

| # | 도구 | 인자 요약 |
|---|------|-----------|
| 1 | `list_sales_views` | – |
| 2 | `get_view_schema` | `dbo.JINJU_SALES` |
| 3 | `get_column_aliases` | `dbo.JINJU_SALES` |
| 4 | `run_sql` | 월별 `SUM(SALES_AMT)` GROUP BY |
| 5 | `run_sql` | `SELECT TOP 3 ITEM_NM ... ORDER BY total_sales_amt DESC` |

- **LIMIT → TOP 확인**: 5번째 쿼리에서 `SELECT TOP 3`을 **1차 시도에 바로** 사용.
  `LIMIT` 생성 및 그로 인한 재시도 왕복 없음(`uvicorn.log`에 "limit" 매치 0건).
- 응답에 마크다운 표 2개 + ` ```chart ` 블록(`type:"line"`, `xKey:"sales_month"`, 숫자형 data) 포함 →
  `ChartRenderer.tsx` 파싱 계약 유지 확인.
- "도구 호출 횟수를 초과했습니다" 폴백 미발생.

## 4. 팀 통신

- frontend-dev: 응답 포맷/chart JSON 스키마 **변경 없음**. 다만 복잡 질의 소요가 ~37초로
  기존보다 길어질 수 있으니 로딩 UX만 참고(프록시 타임아웃 120초 여유 유지).
- mcp-guardian: 도구/뷰/별칭 요청 사항 없음. 이번 변경은 프롬프트+루프 상한만 조정.
- qa-verifier: 144개 통과 상태에서 재검증 요청 가능.
