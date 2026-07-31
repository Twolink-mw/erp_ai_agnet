---
name: chat-ui-dev
description: "챗봇 프론트엔드(frontend/components/Chat.tsx, ChartRenderer.tsx) 작업 절차. 대화 UI 개선, chart JSON 블록 파싱/시각화 로직 수정, 마크다운 렌더링, 로딩/에러 상태 처리 요청 시 사용."
---

# Chat UI Dev

Chat.tsx와 ChartRenderer.tsx는 하나의 계약으로 묶여 있다: 백엔드가 assistant 메시지 안에
` ```chart ` 태그가 붙은 JSON 코드 블록을 심으면, Chat.tsx가 이를 가로채 ChartRenderer로 넘기고
ChartRenderer의 `parseChartSpec`이 파싱해 recharts로 그린다. 이 계약이 어긋나면 컴파일은
멀쩡히 통과하지만 런타임에 차트가 안 뜨거나 원본 JSON 텍스트가 그대로 노출된다.

## 렌더링 흐름

```
assistant 메시지 (마크다운 + ```chart 블록 포함 가능)
  → react-markdown이 일반 텍스트/마크다운 렌더링
  → language-chart 코드 블록만 가로채기
  → ChartRenderer.parseChartSpec(jsonString)
  → 파싱 성공: recharts 컴포넌트로 렌더링
  → 파싱 실패: 원본 텍스트 표시 (크래시 금지)
```

## chart JSON 스키마를 바꿔야 할 때

1. 먼저 backend-dev(또는 `gemini-agent-dev` 스킬의 SYSTEM_PROMPT 절)를 확인해 현재 스키마가 무엇인지 파악한다 — 스키마는 백엔드 시스템 프롬프트가 정의하고, 프론트는 그것을 소비하는 쪽이다.
2. 스키마를 바꾸려면 backend-dev에게 먼저 SendMessage(팀 모드) 또는 사용자에게 확인한다. 한쪽만 바꾸면 정합성이 깨진다.
3. `parseChartSpec`을 수정한 뒤, 구버전 스키마로 온 메시지도 방어적으로 처리되는지 확인한다(과거 대화 로그 재렌더링 가능성).

## 작업 원칙

- 표/차트는 assistant 메시지 안에 자연스럽게 임베드되는 형태를 유지한다. 별도 페이지나 모달로 분리하지 않는다 — 이 프로젝트는 "엑셀 시트를 다루듯" 대화 흐름 안에서 데이터를 확인하는 것이 핵심 UX다.
- 백엔드 응답이 120초까지 걸릴 수 있다(`proxyTimeout`). 로딩 상태를 명확히 표시하고, 짧은 타임아웃으로 요청을 끊지 않는다.
- 한글 UI 톤(챗봇 대화체)을 유지한다.

## 검증

- `npm test` (vitest) — `Chat.test.tsx`, `ChartRenderer.test.tsx`
- 가능하면 `npm run dev`로 실제 브라우저에서 대화 흐름 + 차트 렌더링 골든 패스를 확인한다. 특히: 일반 텍스트 응답, 표 포함 응답, chart 블록 포함 응답, 파싱 실패 시 폴백을 모두 확인한다.
