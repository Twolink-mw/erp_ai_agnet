---
name: erp-sales-harness
description: "사내 ERP 매출 챗봇(FastAPI/MSSQL/MCP/Gemini/Next.js) 프로젝트의 에이전트 팀 오케스트레이터. 새 매출 뷰 추가, 화이트리스트/SQL 가드 수정, Gemini 에이전트 루프/시스템 프롬프트 변경, 챗봇 UI/차트 개선, 새 기능 추가처럼 mcp_server/app/frontend 중 하나 이상을 건드리는 개발 작업 요청 시 사용. 후속 작업(이전 변경 보완, 재검증, 특정 뷰만 다시 추가, 가드 규칙 업데이트, 버그 수정)에도 반드시 이 스킬을 사용."
---

# ERP Sales Harness Orchestrator

이 프로젝트는 3개 코드 계층(mcp_server 보안 가드레일 / app 에이전트 루프 / frontend 챗 UI)이
서로 계약으로 묶여 있다. 오케스트레이터는 요청이 몇 개 계층을 건드리는지 먼저 판단하고,
단일 계층이면 가볍게(서브 에이전트), 여러 계층이면 팀으로 조율한다.

## 실행 모드: 하이브리드

| 상황 | 모드 | 이유 |
|------|------|------|
| 요청이 mcp_server/app/frontend 중 정확히 1개만 건드림 | 서브 에이전트 | 담당 에이전트 1명 + QA 1명이면 충분, 팀 오버헤드 불필요 |
| 요청이 2개 이상 계층을 건드림 (새 뷰+시스템프롬프트, 새 기능 등) | 에이전트 팀 | 계층 간 계약(도구 스키마, chart JSON) 변경이 실시간 조율 없이 진행되면 경계면 불일치 위험 |

## 에이전트 구성

| 에이전트 | 타입 | 역할 | 스킬 | 담당 파일 |
|---------|------|------|------|----------|
| mcp-guardian | 커스텀 | 매출 뷰 화이트리스트/SQL 가드/DB 접근 통제 | sql-guardrail-review | `backend/mcp_server/*` |
| backend-dev | 커스텀 | Gemini 에이전트 루프/FastAPI/MCP 클라이언트 | gemini-agent-dev | `backend/app/*` |
| frontend-dev | 커스텀 | 챗봇 UI/차트 렌더링 | chat-ui-dev | `frontend/*` |
| qa-verifier | 커스텀 (general-purpose 기반) | 테스트 실행 + 경계면 정합성 검증 | erp-integration-qa | `backend/tests/*`, `frontend/**/__tests__/*` |

## 워크플로우

### Phase 0: 컨텍스트 확인 (후속 작업 지원)

1. `_workspace/` 디렉토리 존재 여부 확인
2. 실행 모드 결정:
   - **`_workspace/` 미존재** → 초기 실행. Phase 1로 진행
   - **`_workspace/` 존재 + 부분 수정/재검증 요청** ("이전에 추가한 뷰만 다시", "가드 규칙 보완", "다시 검증") → 부분 재실행. 해당 에이전트만 재호출하고, 기존 산출물 중 수정 대상만 갱신
   - **`_workspace/` 존재 + 새로운 기능/뷰 요청** → 새 실행. 기존 `_workspace/`를 `_workspace_{YYYYMMDD_HHMMSS}/`로 이동한 뒤 Phase 1 진행
3. 부분 재실행 시 이전 산출물 경로를 에이전트 프롬프트에 포함해, 기존 결과를 읽고 피드백을 반영하도록 지시

### Phase 1: 요청 스코프 분석

1. 요청이 언급하는 파일/기능을 통해 어떤 계층(mcp_server / app / frontend)을 건드리는지 판단한다:
   - "매출 뷰 추가", "화이트리스트", "SQL 가드", "한글 별칭" → mcp_server
   - "Gemini 응답", "시스템 프롬프트", "도구 호출 루프", "MCP 클라이언트", "API 엔드포인트" → app
   - "채팅 UI", "차트", "화면", "프론트엔드" → frontend
   - 애매하면 코드베이스를 Grep/Read로 확인 후 판단한다. 확신이 서지 않으면 사용자에게 확인한다.
2. 건드리는 계층 수를 센다. 1개면 Phase 2A(서브 에이전트 경로), 2개 이상이면 Phase 2B(팀 경로)로 진행
3. `_workspace/00_input/scope.md`에 판단 근거를 기록

### Phase 2A: 단일 계층 — 서브 에이전트 경로

**실행 모드:** 서브 에이전트

```
Agent(name: "{해당 담당 에이전트}", subagent_type: "{mcp-guardian|backend-dev|frontend-dev}",
      model: "opus", prompt: "{요청 상세 + 관련 스킬 참조 지시}")
```

완료 후:
```
Agent(name: "qa-verifier", subagent_type: "qa-verifier", model: "opus",
      prompt: "{변경된 파일} 검증. erp-integration-qa 스킬의 해당 경계면 체크리스트 적용")
```

산출물은 `_workspace/01_{agent}_result.md`, `_workspace/02_qa-verifier_report.md`에 저장.
QA가 문제를 발견하면 담당 에이전트를 1회 더 호출해 수정 → 재검증.

### Phase 2B: 다중 계층 — 에이전트 팀 경로

**실행 모드:** 에이전트 팀

1. 팀 생성 (건드리는 계층에 해당하는 에이전트만 포함 + qa-verifier는 항상 포함):
   ```
   TeamCreate(
     team_name: "erp-sales-team",
     members: [
       { name: "mcp-guardian", agent_type: "mcp-guardian", model: "opus", prompt: "{화이트리스트/가드 관련 작업 지시}" },
       { name: "backend-dev", agent_type: "backend-dev", model: "opus", prompt: "{에이전트 루프/프롬프트 작업 지시}" },
       { name: "frontend-dev", agent_type: "frontend-dev", model: "opus", prompt: "{UI/차트 작업 지시}" },
       { name: "qa-verifier", agent_type: "qa-verifier", model: "opus", prompt: "{각 팀원 완료 즉시 점진적 검증}" }
     ]
   )
   ```
   (해당 없는 계층의 에이전트는 팀 구성에서 제외한다)

2. 작업 등록:
   ```
   TaskCreate(tasks: [
     { title: "화이트리스트/가드 변경", assignee: "mcp-guardian" },
     { title: "에이전트 루프/프롬프트 반영", assignee: "backend-dev", depends_on: ["화이트리스트/가드 변경"] },
     { title: "UI/차트 반영", assignee: "frontend-dev", depends_on: ["에이전트 루프/프롬프트 반영"] },
     { title: "경계면 검증", assignee: "qa-verifier", depends_on: ["화이트리스트/가드 변경", "에이전트 루프/프롬프트 반영", "UI/차트 반영"] }
   ])
   ```
   실제 의존 관계는 요청 내용에 따라 조정한다 (예: 프론트만 chart 스키마를 바꾸는 요청이면 backend-dev→frontend-dev 순서, mcp-guardian은 불참).

3. **팀원 간 통신 규칙:**
   - mcp-guardian은 화이트리스트/별칭 변경 완료 시 backend-dev에게 SendMessage (시스템 프롬프트/도구 스키마 영향 확인 요청)
   - backend-dev는 응답 포맷(chart JSON 등) 변경 시 frontend-dev에게 SendMessage
   - qa-verifier는 각 팀원의 작업 완료 알림을 받는 즉시 해당 영역만 점진적으로 검증하고, 경계면 불일치 발견 시 관련된 양쪽 에이전트 모두에게 SendMessage로 구체적 수정 요청(파일:라인 포함)

4. **산출물 저장:**

   | 팀원 | 출력 경로 |
   |------|----------|
   | mcp-guardian | `_workspace/01_mcp-guardian_summary.md` |
   | backend-dev | `_workspace/02_backend-dev_summary.md` |
   | frontend-dev | `_workspace/03_frontend-dev_summary.md` |
   | qa-verifier | `_workspace/04_qa-verifier_report.md` |

5. 리더는 TaskGet으로 진행률을 모니터링하고, 팀원이 유휴 상태가 되거나 막히면 SendMessage로 개입한다.

### Phase 3: 통합 및 정리

1. 모든 작업 완료 대기 (TaskGet)
2. qa-verifier의 최종 리포트를 Read로 확인 — 실패/미검증 항목이 있으면 해당 담당 에이전트에게 1회 재작업 요청
3. 재작업 후에도 실패가 남으면 사용자에게 명시적으로 보고하고 진행 여부를 확인 (임의로 "완료"로 보고하지 않는다)
4. 팀 모드였다면: 팀원 종료 요청(SendMessage) → `TeamDelete`
5. `_workspace/` 보존 (감사 추적용)
6. 사용자에게 결과 요약 보고: 변경된 파일, 통과한 검증, 남은 이슈

## 에러 핸들링

| 상황 | 전략 |
|------|------|
| 담당 에이전트 1명 실패/중지 | 리더가 감지 → SendMessage로 상태 확인 → 재시작. 재실패 시 해당 계층 변경 없이 진행하고 최종 보고에 누락 명시 |
| qa-verifier가 가드레일 우회 가능성 발견 | 최우선 처리 — 다른 작업보다 먼저 mcp-guardian에게 즉시 알리고 수정 완료 전까지 해당 변경을 "완료"로 보고하지 않는다 |
| 경계면 불일치(chart 스키마, 도구 스키마 등) | 관련 양쪽 에이전트 모두에게 통보, 어느 쪽이 "정답"인지 판단 후 반대쪽을 맞춘다 |
| 타임아웃/응답 지연 | 현재까지 수집된 부분 결과 사용, 미완료 작업은 다음 세션에서 `_workspace/` 기반으로 이어감 |
| 서로 다른 계층 에이전트 간 데이터 충돌 | 삭제하지 않고 출처(어느 에이전트, 언제) 병기 |

## 테스트 시나리오

### 정상 흐름 (단일 계층)
1. 사용자가 "SALES.vw_monthly_summary 뷰를 화이트리스트에 추가하고 '월별요약'이라는 별칭을 붙여줘" 요청
2. Phase 1에서 mcp_server 계층 1개만 해당한다고 판단 → Phase 2A
3. mcp-guardian 서브 에이전트가 `sql-guardrail-review` 스킬을 따라 화이트리스트/별칭 추가
4. qa-verifier 서브 에이전트가 `test_views_whitelist.py`, `test_sql_guard.py` 실행 + 우회 시나리오 테스트
5. 통과 → `_workspace/`에 결과 저장, 사용자에게 요약 보고

### 정상 흐름 (다중 계층)
1. 사용자가 "지역별 매출 비교 시 자동으로 막대 차트를 보여주는 기능 추가해줘" 요청
2. Phase 1에서 app(시스템 프롬프트) + frontend(차트 렌더링) 2개 계층 해당 → Phase 2B
3. TeamCreate로 backend-dev + frontend-dev + qa-verifier 팀 구성 (mcp-guardian 불참)
4. backend-dev가 SYSTEM_PROMPT에 chart 블록 출력 지시를 구체화하고 frontend-dev에게 스키마 SendMessage
5. frontend-dev가 ChartRenderer에서 해당 스키마 처리 확인/보완
6. qa-verifier가 양쪽을 교차 검증, 통과
7. 팀 정리, 결과 보고

### 에러 흐름
1. Phase 2B에서 qa-verifier가 "화이트리스트에는 있지만 sql_guard의 테이블 검사 정규식이 대괄호 표기를 놓쳐 새 뷰가 거부된다"는 경계면 불일치 발견
2. qa-verifier가 mcp-guardian에게 파일:라인과 함께 SendMessage
3. mcp-guardian이 정규식 수정 → qa-verifier 재검증
4. 통과 후에만 "완료"로 최종 보고
