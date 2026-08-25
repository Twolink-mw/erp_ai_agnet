# ERP 매출 분석 챗봇 개발 보고서

- 보고일: 2026-08-24
- 대상: 개발자, 사용자
- 기준: 현재 저장소의 구현 코드, 개발 요약 문서, QA 검증 결과
- 변경 원칙: 본 보고서 작성 과정에서는 개발 소스 파일을 수정하지 않음

## 1. 전체 요약

ERP의 매출 데이터를 자연어로 조회하고 분석하는 웹 챗봇의 주요 기능이 구현되어 있다.
사용자 질문은 Next.js 프론트엔드에서 FastAPI 백엔드로 전달되고, Gemini 에이전트가 MCP 도구를 통해 허용된 MS-SQL 매출 뷰를 조회한다. 조회 결과는 대화 응답, 표, 차트로 제공된다.

현재 확인된 자동화 테스트 결과는 다음과 같다.

- 백엔드 pytest: **225건 통과 / 225건**
- 프론트엔드 Vitest: **52건 통과 / 52건**
- 실제 DB/Gemini 연결이 필요한 수동 점검 스크립트: 환경 의존성으로 미실행

## 2. 개발자 대상 보고

### 2.1 시스템 구성

| 계층 | 주요 역할 | 주요 파일 |
|---|---|---|
| Frontend | 채팅 화면, 표·차트 렌더링, PDF 다운로드, 이메일 발송 UI | [frontend/components/Chat.tsx](../frontend/components/Chat.tsx), [frontend/components/ChartRenderer.tsx](../frontend/components/ChartRenderer.tsx) |
| App Backend | FastAPI API, Gemini 도구 호출 루프, MCP 세션 관리 | [backend/app/main.py](../backend/app/main.py), [backend/app/gemini_agent.py](../backend/app/gemini_agent.py), [backend/app/mcp_client.py](../backend/app/mcp_client.py) |
| MCP/DB | 도구 제공, SQL 검증, 허용 뷰 조회, MS-SQL 연결 | [backend/mcp_server/server.py](../backend/mcp_server/server.py), [backend/mcp_server/sql_guard.py](../backend/mcp_server/sql_guard.py), [backend/mcp_server/views_whitelist.py](../backend/mcp_server/views_whitelist.py) |
| Report | 기존 챗봇 응답을 PDF로 렌더링하고 SMTP로 발송 | [backend/app/pdf_report.py](../backend/app/pdf_report.py), [backend/app/mailer.py](../backend/app/mailer.py) |

### 2.2 구현 완료 기능

#### 자연어 기반 매출 조회

- Gemini 에이전트가 MCP 도구를 호출해 매출 뷰와 스키마를 확인한 뒤 SQL을 실행한다.
- MCP 도구 정의는 동적으로 Gemini FunctionDeclaration으로 변환된다.
- MCP 세션은 요청 단위로 생성·종료하는 구조를 유지한다.
- 정상 응답과 오류 응답 모두 `reply`, `tool_calls` 형식의 반환 계약을 유지한다.

#### SQL 보안 가드레일

- 사전에 승인된 매출 뷰만 조회할 수 있도록 화이트리스트를 적용한다.
- SELECT 단일 문장만 허용한다.
- INSERT, UPDATE, DELETE, DROP 등 DML/DDL과 다중 문장을 차단한다.
- CTE는 허용하되, CTE 내부의 비화이트리스트 뷰 참조는 차단한다.
- TOP 절이 없는 조회에는 최대 1,000행 제한을 적용한다.
- DB 계정도 허용된 뷰에 대한 SELECT 권한만 갖도록 운영하는 전제를 둔다.

#### 환각 및 코드 덤프 방어

- 실제 도구 호출 없이 수치성 표·차트 응답을 생성하는 경우를 감지한다.
- Python, SQL 등 chart 이외의 코드 블록이 응답에 섞이는 경우를 감지한다.
- 방어 재시도는 최대 도구 라운드 예산 안에서 수행되며 무한 루프가 발생하지 않는다.
- 재시도 한도 초과 시 근거 없는 결과나 코드 덤프를 그대로 노출하지 않고 안내 문구를 반환한다.

#### 차트 및 순위 변동 표시

- 백엔드 시스템 프롬프트와 프론트엔드 파서가 다음 chart JSON 계약을 공유한다.
  `type`, `title`, `xKey`, `series`, `data`
- 막대·선 차트와 표 렌더링을 지원한다.
- 표의 순위 변동 값 `▲숫자`와 `▼숫자`를 테마별 색상 토큰으로 표시한다.
- 라이트·다크 테마 모두 순위 상승·하락 색상이 정의되어 있다.

#### PDF 및 이메일 리포트

- 챗봇 응답에 표 또는 차트가 있으면 PDF 다운로드와 이메일 발송을 사용할 수 있다.
- PDF·이메일 기능은 새 SQL을 실행하지 않고 `/api/chat` 응답을 그대로 재사용한다.
- 이메일 API는 여러 수신자 배열을 지원한다.
- 수신자는 형식 및 `ALLOWED_EMAIL_DOMAINS` 화이트리스트를 모두 검증한다.
- `.env`의 `EMAIL_PRESET_RECIPIENTS`로 자주 사용하는 수신자 목록을 설정할 수 있다.
- `GET /api/report/email/presets`는 항상 `{"presets": [...]}`를 반환한다.
- 프론트엔드에서 프리셋 수신자를 여러 명 체크할 수 있고, 직접 입력 주소와 병합·중복 제거해 발송한다.
- SMTP 미설정 시 이메일 발송은 비활성화되지만, 프리셋 조회 API는 빈 배열로 정상 응답한다.

### 2.3 API 및 설정 계약

- `POST /api/chat`: 자연어 대화 및 매출 분석
- `POST /api/report/pdf`: 기존 응답을 PDF로 변환
- `POST /api/report/email`: 기존 응답을 PDF 첨부 이메일로 발송
- `GET /api/report/email/presets`: 이메일 프리셋 목록 조회
- 이메일 관련 설정: `SMTP_*`, `ALLOWED_EMAIL_DOMAINS`, `EMAIL_PRESET_RECIPIENTS`
- 프론트엔드는 chart JSON의 필드명과 타입이 변경되지 않는다는 계약에 의존한다.

### 2.4 검증 결과

- 백엔드 전체 테스트: **225/225 통과**
- 프론트엔드 전체 테스트: **52/52 통과**
- SQL 가드 우회 시나리오, CTE, 다중 문장, 비허용 뷰 접근 차단 검증 완료
- MCP 도구와 Gemini FunctionDeclaration 간 동적 변환 계약 검증 완료
- chart JSON과 프론트 파서 간 필드 정합성 검증 완료
- 이메일 프리셋 API와 멀티 수신자 발송 흐름 검증 완료
- 실제 DB/Gemini 수동 스크립트는 접속 정보와 외부 서비스가 필요하므로 실행하지 않음

### 2.5 잔여 이슈 및 개선 권고

차단성 결함은 확인되지 않았으나 다음 항목은 후속 개선 대상으로 남아 있다.

1. [frontend/components/ChartRenderer.tsx](../frontend/components/ChartRenderer.tsx)에 기존 `recharts Formatter` TypeScript 오류 1건이 있다. 이번 기능 변경으로 발생한 오류는 아니다.
2. 순위 변동 SQL 힌트에서 큰 순위 차이를 처리할 수 있도록 `NVARCHAR(2)`를 더 넉넉한 길이로 확장하는 개선이 권고되었다.
3. 코드 블록 방어 정규식은 현재 백틱 3개 형식을 대상으로 하며, 틸드 펜스와 4개 이상 백틱 펜스까지 확장할 여지가 있다.
4. `.env`의 이메일 프리셋에 동일 주소가 중복 등록되지 않도록 설정 검증을 추가할 수 있다.
5. 운영 배포 전에는 실제 MS-SQL, Gemini API, SMTP 환경에서 수동 스모크 테스트가 필요하다.

## 3. 사용자 대상 보고

### 3.1 사용자가 할 수 있는 일

- 자연어로 매출 데이터를 질문할 수 있다.
- 기간, 상품, 거래처, 매출 규모 등 업무 기준으로 데이터를 요청할 수 있다.
- 조회 결과를 대화형 답변과 표로 확인할 수 있다.
- 적합한 결과는 막대 차트 또는 선 차트로 확인할 수 있다.
- 순위가 오른 항목과 내려간 항목을 색상으로 구분할 수 있다.
- 결과가 포함된 대화를 PDF로 다운로드할 수 있다.
- 결과를 여러 이메일 수신자에게 한 번에 보낼 수 있다.
- 자주 사용하는 사내 수신자는 체크 목록에서 여러 명 선택할 수 있다.
- 체크 목록에 없는 수신자도 직접 입력할 수 있다.

### 3.2 기본 사용 흐름

1. 채팅 화면에서 매출 관련 질문을 입력한다.
2. AI가 승인된 매출 데이터를 조회하고 결과를 표 또는 차트로 표시한다.
3. 필요한 경우 PDF 다운로드 또는 이메일 발송을 선택한다.
4. 이메일 발송 시 프리셋 수신자를 여러 명 선택하거나 직접 이메일 주소를 입력한다.
5. 시스템이 수신자 형식과 허용 도메인을 확인한 뒤 발송한다.

### 3.3 사용자 보호 및 제한

- 시스템은 승인된 매출 데이터 범위 안에서만 조회한다.
- 원본 테이블에 직접 접근하지 않고 읽기 전용 조회만 수행한다.
- 허용되지 않은 이메일 도메인으로는 발송할 수 없다.
- 실제 데이터 조회가 확인되지 않은 응답은 결과로 단정해 표시하지 않는다.
- 이메일 프리셋은 편의를 위한 추천 목록이며, 발송 허용 여부를 대신하지 않는다.
- SMTP 설정이 완료되지 않은 환경에서는 이메일 발송을 사용할 수 없다.

### 3.4 사용자 관점의 현재 상태

주요 조회, 표·차트 표시, PDF 및 이메일 리포트, 다중 수신자 선택 기능은 자동화 테스트 기준으로 정상 동작이 확인되었다. 실제 서비스 사용을 위해서는 운영 환경의 Gemini API, MS-SQL, SMTP 설정이 필요하다.

## 4. 운영 전 확인 사항

- 백엔드와 프론트엔드 서버가 모두 실행되는지 확인
- MS-SQL ODBC Driver 및 접속 정보 확인
- `GEMINI_API_KEY`와 `MSSQL_*` 환경변수 설정
- 이메일 사용 시 SMTP 설정 및 `ALLOWED_EMAIL_DOMAINS` 설정
- 실제 운영 데이터로 대표 질문과 이메일 발송을 각각 1회 이상 확인
- 보안 가드 또는 허용 뷰를 변경한 경우 전체 pytest와 경계면 검증을 다시 수행

## 5. 참고 문서

- [README.md](../README.md)
- [프로젝트 개발 기준](../CLAUDE.md)
- [백엔드 개발 요약](../_workspace/01_backend-dev_summary.md)
- [프론트엔드 개발 요약](../_workspace/03_frontend-dev_summary.md)
- [QA 최종 검증 보고서](../_workspace/04_qa-verifier_report_rank-color.md)
- [코드 덤프 방지 QA 보고서](../_workspace/04_qa-verifier_report_code-dump.md)
- [이메일 프리셋 QA 보고서](../_workspace/04_qa-verifier_report_email-preset.md)
