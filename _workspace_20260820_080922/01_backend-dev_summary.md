# 01 · backend-dev — 매출 조회 결과 PDF 리포트 백엔드

## 변경/추가한 파일

| 파일 | 내용 |
| --- | --- |
| `backend/app/pdf_report.py` | **신규.** 순수 렌더링 계층 — 마크다운 최소 파서, ```chart 블록 파서, reportlab PDF 조립, 파일명 새니타이즈, `has_reportable_content()` 힌트 |
| `backend/app/main.py` | `POST /api/report/pdf` 추가, `ChatResponse.report_available` 옵셔널 필드 추가, CORS `expose_headers=["Content-Disposition"]` |
| `backend/app/config.py` | `SYSTEM_PROMPT`에 "PDF/리포트 요청 처리" 지시 추가 |
| `backend/requirements.txt` | `reportlab==4.4.4` 추가 (순수 파이썬 + pillow, 시스템 라이브러리 불필요) |
| `backend/tests/test_pdf_report.py` | **신규.** 18개 테스트 |

변경하지 않은 것: `mcp_server/` 전체(화이트리스트/SQL 가드/도구 스키마), `gemini_agent.py`, `mcp_client.py`, `frontend/`.

## 엔드포인트 스펙

### `POST /api/report/pdf`

**Request** — `application/json`, 모든 필드 옵셔널:

```jsonc
{
  "title":   "2026 상반기 매출 리포트",   // string|null, 기본 "ERP 매출 분석 리포트"
  "question":"상반기 월별 매출 추이 보여줘", // string|null, 부제로 "질문: ..." 표기
  "content": "…챗봇 응답 마크다운 원문…",   // string, 기본 ""
  "tables":  [ { "title": "월별", "columns": ["월","매출"], "rows": [["1월", 2000000]] } ],
  "charts":  [ { "type":"bar"|"line", "title":"…", "xKey":"월",
                 "series":[{"key":"매출","name":"매출액"}],
                 "data":[{"월":"1월","매출":2000000}] } ],
  "generated_at": "2026-08-20 14:30",     // string|null, 기본 서버 현재시각
  "filename": "매출리포트.pdf"             // string|null, 기본 sales_report_YYYYMMDD_HHMMSS.pdf
}
```

**Response** — `200`, `Content-Type: application/pdf` 바이너리 body.
헤더: `Content-Disposition: attachment; filename="<ascii>"; filename*=UTF-8''<pct-encoded>`,
`Content-Length`, `Cache-Control: no-store`.
실패 시 `500 {"detail": "PDF 생성에 실패했습니다."}` — 내부 경로/스택 미노출.
바디 스키마 위반은 FastAPI 기본 `422`.

**핵심**: `content` 하나만 보내면 충분하다. 마지막 assistant 메시지 원문을 그대로 넣으면
백엔드가 제목(`#`), 문단, 불릿, 마크다운 표, ```chart 블록을 알아서 파싱해 렌더링한다.
`tables`/`charts`는 프론트가 이미 구조화해 들고 있는 데이터를 **추가로** 덧붙이고 싶을 때만 쓴다
(content 파싱 결과 뒤에 append됨 — 둘 다 보내면 중복 렌더링).

## ChatResponse 스키마 변경

```python
class ChatResponse(BaseModel):
    reply: str
    tool_calls: list[dict]
    report_available: bool = False   # 신규, 옵셔널(기본 False)
```

`reply`에 마크다운 표 또는 ```chart 블록이 있으면 `true`. 프론트가 "PDF 다운로드" 버튼
노출 여부를 판단하는 **힌트일 뿐**이며, `/api/report/pdf`는 이 값과 무관하게 어떤 content든 렌더링한다.
기존 필드는 그대로이므로 프론트를 수정하지 않아도 동작한다.

## 시스템 프롬프트 추가 지시 (요약)

"PDF로 만들어줘 / 리포트로 저장해줘 / 출력해줘" 요청 시:
- **도구 재호출·새 SQL 실행 금지**, 직전 대화의 조회 결과를 그대로 재사용
- `#` 제목 한 줄로 시작
- 직전 답변의 요약·마크다운 표·```chart 블록을 빠짐없이 다시 포함
- 마지막에 "아래 PDF 다운로드 버튼으로 저장할 수 있습니다." 안내
- 직전 대화에 조회 결과가 없으면 무엇을 조회할지 되묻기

기존 두 불변 지시(별칭 해석 → 실제 DB 이름, ```chart 블록 출력)는 그대로 유지.

## 보안

- PDF 경로는 DB/MCP/SQL을 전혀 호출하지 않는다. 데이터는 100% 요청 본문에서 온다.
  회귀 테스트 `test_report_pdf_endpoint_does_not_touch_mcp`로 고정.
- Paragraph 마크업 주입 방지: 모든 텍스트를 XML 이스케이프한 뒤 인라인 마크다운을 적용.
- `safe_filename()`이 경로 구분자·`..`·제어문자를 제거 (파일을 디스크에 쓰지는 않지만 헤더 위생 목적).

## 구현 노트

- 한글 폰트는 reportlab 내장 Adobe CID 폰트(`HYSMyeongJo-Medium` 본문 / `HYGothic-Medium` 강조)를 사용 —
  외부 TTF 배포 불필요. 등록 실패 시 Helvetica 폴백(한글은 깨지되 PDF 생성은 성공).
- 차트는 `reportlab.graphics`의 VerticalBarChart / HorizontalLineChart로 실제 그려진다(추가 의존성 없음).
  팔레트는 `ChartRenderer.tsx`의 라이트 테마 8색과 동일 순서. 그리기 실패 시 데이터 표로 폴백.
- 깨진 ```chart JSON은 크래시 대신 코드 블록으로 원문 보존.

## frontend-dev 통합 포인트

1. `next.config.js` **수정 불필요** — 기존 `/api/:path*` rewrite가 `/api/report/pdf`를 이미 커버.
2. 최소 연동:
   ```ts
   const res = await fetch("/api/report/pdf", {
     method: "POST",
     headers: { "Content-Type": "application/json" },
     body: JSON.stringify({ title, question: lastUserMessage, content: lastAssistantMessage }),
   });
   const blob = await res.blob();          // res.ok 체크 필수 (500 시 JSON detail)
   const url = URL.createObjectURL(blob);  // <a download> 후 revokeObjectURL
   ```
   파일명은 `Content-Disposition`에서 파싱 가능(CORS expose 처리됨) — 없으면 자체 생성.
3. `ChatResponse.report_available`(boolean, 옵셔널)로 버튼 노출 제어 권장.
   구버전 응답에 없을 수 있으니 `res.report_available ?? false`로 방어.
4. ```chart JSON 스키마는 **변경 없음** — ChartRenderer 수정 불필요.
   백엔드 PDF도 동일 스키마(`type`/`title`/`xKey`/`series[].key,name`/`data[]`)를 파싱하므로,
   이 스키마를 바꾸려면 양쪽을 함께 바꿔야 한다.

## 검증

`backend/tests` 전체 **117 passed** (기존 99 + 신규 18). 기존 테스트 회귀 없음.
