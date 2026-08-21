"""LLM이 생성한 SQL을 실행 전에 검증하는 가드레일.

원칙:
- SELECT 단일 문장만 허용 (세미콜론으로 이어진 다중 문장 금지)
  - 단, `WITH <cte> AS (...) SELECT ...` 형태의 CTE(공통 테이블 표현식)는 예외적으로
    허용한다 — 최종적으로 하나의 SELECT로 귀결되는 읽기 전용 쿼리이기 때문. CTE 본문/
    바깥 쿼리 어디에도 DML/DDL이 없어야 하는 것은 동일하게 강제된다(아래 참고).
- FROM/JOIN/APPLY 대상은 화이트리스트에 등록된 뷰만 허용 (수식/비수식 모두 검사,
  CTE 본문 내부의 FROM/JOIN도 동일하게 검사됨 — 쿼리 전체를 스캔하기 때문)
- DDL/DML(SELECT ... INTO 포함) 및 위험 키워드/시스템 프로시저 호출 금지
  (CTE 본문에 숨겨도 전체 쿼리 문자열을 검사하므로 동일하게 차단됨)
- 결과 행수 상한 강제 (TOP 절 누락 시 자동 삽입). CTE 쿼리는 CTE 정의가 모두 끝난
  뒤의 최종(바깥쪽) SELECT에 삽입한다 — CTE 정의 안의 SELECT에 잘못 꽂히면 결과
  집합 자체는 제한되지 않기 때문.
"""

import re

from .views_whitelist import (
    DEFAULT_SCHEMA,
    SALES_VIEW_WHITELIST,
    is_view_allowed,
    rewrite_query_with_aliases,
)

MAX_ROWS = 1000

_FORBIDDEN_KEYWORDS = re.compile(
    # INTO: `SELECT ... INTO NewTable FROM ...`는 SELECT처럼 보이지만 테이블을 생성하는
    # 쓰기 작업이다. 이 프로젝트의 정상 조회 쿼리에는 등장하지 않으므로 차단한다.
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|MERGE|TRUNCATE|CREATE|EXEC|EXECUTE|INTO|"
    r"GRANT|REVOKE|xp_cmdshell|sp_executesql|OPENROWSET|OPENQUERY|OPENDATASOURCE)\b",
    re.IGNORECASE,
)

# T-SQL의 select 절 문법은 `SELECT [ALL | DISTINCT] [TOP (n)] <select_list>` 이다.
# 즉 TOP은 DISTINCT/ALL "뒤"에 와야 한다 (`SELECT DISTINCT TOP 10 x` 가 정상이고
# `SELECT TOP 10 DISTINCT x` 는 문법 오류 156). 이전 구현은 SELECT 바로 뒤의 TOP만
# 인식해서, DISTINCT가 끼면 (1) 이미 있는 TOP을 놓치고 (2) TOP을 DISTINCT 앞에
# 삽입해 실행 불가능한 SQL을 만들었다. 아래 두 패턴은 선택적 ALL/DISTINCT 한정자를
# 함께 인식해 세 경우(TOP 있음 / DISTINCT만 / 둘 다 없음)를 모두 올바르게 처리한다.
_SELECT_QUALIFIER = r"(?:\s+(?:ALL|DISTINCT)\b)?"

_TOP_PATTERN = re.compile(
    r"^\s*SELECT\b" + _SELECT_QUALIFIER + r"\s*TOP\s*\(?\s*\d+\s*\)?",
    re.IGNORECASE,
)

# TOP 삽입 지점: SELECT(+ 있으면 ALL/DISTINCT) 직후. 뒤따르는 공백까지 소비한 뒤
# 한 칸으로 정규화하므로 `SELECT DISTINCT(COL)` 처럼 공백이 없는 형태에서도
# `SELECT DISTINCT TOP 1000 (COL)` 로 안전하게 삽입된다.
_SELECT_PREFIX_PATTERN = re.compile(
    r"^(\s*)SELECT\b(" + _SELECT_QUALIFIER + r")\s*",
    re.IGNORECASE,
)

# --- 테이블 참조 추출 ---------------------------------------------------------
# 이전 구현은 "FROM/JOIN + schema.name" 형태만 매칭했기 때문에 비수식(unqualified)
# 이름(FROM SecretTable)과 콤마 구분 테이블 목록(FROM dbo.A, SecretTable)이
# 아예 캡처되지 않아, 화이트리스트 뷰가 하나라도 함께 참조되면 검사가 성립한 것처럼
# 보이면서 통째로 우회됐다. 아래 파서는 FROM/JOIN 뒤의 "테이블 참조 목록 전체"를
# 잘라내어 콤마로 분리하고, 각 참조의 첫 토큰을 수식 여부와 무관하게 모두 검사한다.
#
# APPLY는 T-SQL에서 우변이 FROM/JOIN과 동일한 table_source이므로 구간 "시작" 키워드에도
# 포함해야 한다(CROSS/OUTER APPLY 뒤 임의 테이블명이 올 수 있음). 동시에 아래
# _CLAUSE_END_PATTERN에도 남겨두어야 선행 FROM 구간이 APPLY에서 끊긴다.
_TABLE_SOURCE_PATTERN = re.compile(r"\b(?:FROM|JOIN|APPLY)\b", re.IGNORECASE)

# 테이블 참조 목록이 끝나는 지점(다음 절의 시작 또는 괄호 닫힘).
_CLAUSE_END_PATTERN = re.compile(
    r"\b(?:ON|WHERE|GROUP|ORDER|HAVING|UNION|EXCEPT|INTERSECT|"
    r"INNER|LEFT|RIGHT|FULL|CROSS|OUTER|APPLY|JOIN|FROM|SELECT|"
    r"PIVOT|UNPIVOT|OPTION|WITH|FOR|GO)\b|\)",
    re.IGNORECASE,
)

# 참조 조각에서 실제 테이블 토큰(별칭 앞의 첫 토큰). 괄호/콤마/공백에서 끊는다.
_REF_TOKEN_PATTERN = re.compile(r"[^\s,()]+")

# 문자열 리터럴 / 주석 마스킹용. 대괄호 식별자를 먼저 소비해서
# `[we'ird]` 같은 식별자 안의 따옴표가 리터럴 스캔을 어긋나게 하지 못하도록 한다.
# (대괄호 구간은 마스킹하지 않고 원문 그대로 보존 — 테이블명일 수 있으므로.)
_NON_CODE_PATTERN = re.compile(
    r"\[(?:\]\]|[^\]])*\]"      # [bracketed identifier] — 보존
    r"|'(?:''|[^'])*'"          # 'string literal'      — 마스킹
    r"|--[^\n]*"                # -- 한 줄 주석          — 마스킹
    r"|/\*.*?\*/",              # /* 블록 주석 */        — 마스킹
    re.DOTALL,
)


def _mask_non_code(q: str) -> str:
    """문자열 리터럴과 주석을 같은 길이의 공백으로 치환한 사본을 만든다.

    길이가 보존되므로 이 사본에서 찾은 오프셋을 원본 쿼리에 그대로 적용할 수 있다.
    이렇게 해야 `WHERE CUST_NM = 'JOIN Corp'` 같은 정상 쿼리에서 리터럴 안의
    FROM/JOIN이 테이블 참조로 오인되지 않는다(오탐 제거). 마스킹된 구간은 SQL에서
    실행되지 않는 부분이므로 여기에 테이블 참조를 숨기는 우회는 성립하지 않는다.
    """

    def replace(match: re.Match) -> str:
        text = match.group(0)
        if text.startswith("["):
            return text
        return " " * len(text)

    return _NON_CODE_PATTERN.sub(replace, q)


def _split_identifier_parts(token: str) -> list[str]:
    """수식된 식별자를 점(.) 기준으로 분해한다. 대괄호/따옴표 안의 점은 구분자가 아니다.

    `[dbo.JINJU_SALES]`는 두 부분 참조가 아니라 이름에 점이 들어간 단일 식별자다.
    """
    parts: list[str] = []
    current: list[str] = []
    index = 0
    length = len(token)
    while index < length:
        char = token[index]
        if char in "[\"":
            closing = "]" if char == "[" else '"'
            index += 1
            while index < length:
                if token[index] == closing:
                    # ]] / "" 는 이스케이프된 닫는 문자
                    if index + 1 < length and token[index + 1] == closing:
                        current.append(closing)
                        index += 2
                        continue
                    index += 1
                    break
                current.append(token[index])
                index += 1
            continue
        if char == ".":
            parts.append("".join(current))
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    parts.append("".join(current))
    return parts


def _iter_table_refs(q: str):
    """FROM/JOIN/APPLY 뒤에 오는 모든 테이블 참조 토큰을 (start, end, token)으로 순회한다.

    - `q`는 `_mask_non_code()`를 거친 사본을 받는다(오프셋은 원본과 1:1).
    - `FROM (SELECT ...) t` 같은 파생 테이블은 토큰이 없으므로 건너뛰고,
      내부의 FROM은 자기 자신의 FROM 매치에서 별도로 검사된다.
    - `FROM a, b` 형태의 콤마 목록은 각 항목이 개별 참조로 잡힌다.
    """
    for keyword_match in _TABLE_SOURCE_PATTERN.finditer(q):
        segment_start = keyword_match.end()
        end_match = _CLAUSE_END_PATTERN.search(q, segment_start)
        segment_end = end_match.start() if end_match else len(q)
        segment = q[segment_start:segment_end]

        offset = 0
        for part in segment.split(","):
            part_start = segment_start + offset
            offset += len(part) + 1
            token_match = _REF_TOKEN_PATTERN.search(part)
            if not token_match:
                # 파생 테이블/서브쿼리 등 실제 이름이 없는 조각
                continue
            yield (
                part_start + token_match.start(),
                part_start + token_match.end(),
                token_match.group(0),
            )


def _resolve_reference(token: str) -> tuple[str, bool]:
    """참조 토큰을 정규화된 'schema.name'과 '비수식 여부'로 변환한다.

    비수식 이름은 MSSQL의 기본 스키마 해석을 반영해 DEFAULT_SCHEMA로 보충한다.
    3부분 이상(교차 DB/링크드 서버) 참조는 허용하지 않는다.
    """
    parts = [p.strip() for p in _split_identifier_parts(token)]
    if not all(parts) or any("." in p for p in parts):
        # 빈 파트(`dbo..X`)이거나, `[dbo.JINJU_SALES]`처럼 이름 자체에 점이 든
        # 단일 식별자 — 화이트리스트의 schema.view와 대응시킬 수 없으므로 거부한다.
        raise SqlGuardError(f"'{token}' 은(는) 해석할 수 없는 테이블 참조입니다.")

    if len(parts) == 1:
        return f"{DEFAULT_SCHEMA}.{parts[0]}", True
    if len(parts) == 2:
        return f"{parts[0]}.{parts[1]}", False

    raise SqlGuardError(
        f"'{token}' 처럼 3부분 이상으로 수식된(교차 DB/링크드 서버) 참조는 허용되지 않습니다."
    )


def _check_and_qualify_table_refs(q: str, cte_names: frozenset[str] = frozenset()) -> str:
    referenced: list[str] = []
    replacements: list[tuple[int, int, str]] = []

    # 리터럴/주석을 마스킹한 사본에서 참조를 찾는다. 오프셋은 원본과 동일하므로
    # 아래 수식화 치환은 원본 q에 그대로 적용한다.
    for start, end, token in _iter_table_refs(_mask_non_code(q)):
        # CTE로 정의된 이름을 비수식(점 없이) 그대로 참조하는 경우는 실제 DB 객체가
        # 아니라 이 쿼리 안에서만 유효한 로컬 별칭이다 — SQL Server 자체도 CTE 이름이
        # 실제 테이블명을 가리도록(shadow) 동작하므로, 화이트리스트 검사 대상에서
        # 제외해도 새로운 접근 권한이 생기지 않는다(CTE 본문 안의 FROM/JOIN은 이
        # 함수가 별도로, 예외 없이 검사한다). 점으로 수식된 참조(`dbo.ranked`)는
        # CTE를 가리킬 수 없으므로 이 예외에서 제외한다.
        if "." not in token and token.strip("[]\"").lower() in cte_names:
            continue

        view_name, was_unqualified = _resolve_reference(token)
        if not is_view_allowed(view_name):
            raise SqlGuardError(
                f"'{view_name}' 은(는) 허용된 매출 뷰 목록에 없습니다. "
                f"허용된 뷰: {', '.join(sorted(SALES_VIEW_WHITELIST))}"
            )
        referenced.append(view_name)
        if was_unqualified:
            # 실행 계정의 기본 스키마가 무엇이든 화이트리스트 뷰로만 해석되도록
            # 명시적으로 수식해서 내보낸다.
            replacements.append((start, end, view_name))

    if not referenced:
        raise SqlGuardError("FROM 절에서 대상 뷰를 확인할 수 없습니다.")

    for start, end, replacement in reversed(replacements):
        q = q[:start] + replacement + q[end:]

    return q


class SqlGuardError(ValueError):
    pass


_WITH_START_PATTERN = re.compile(r"^\s*WITH\b", re.IGNORECASE)
_CTE_AS_OPEN_PATTERN = re.compile(r"\bAS\s*\(", re.IGNORECASE)
_CTE_IDENTIFIER_PATTERN = re.compile(r"\[[^\]]+\]|\"[^\"]+\"|\w+")


def _parse_cte_definitions(q: str) -> tuple[int, frozenset[str]]:
    """CTE(`WITH a AS (...), b AS (...) SELECT ...`)를 스캔해서
    (바깥쪽 최종 SELECT 시작 인덱스, 정의된 CTE 이름 집합)을 반환한다.

    `q`는 문자열 리터럴/주석이 공백으로 마스킹된 사본이어야 한다(오프셋은 원본과
    1:1이므로 반환값을 원본 쿼리에 그대로 사용할 수 있다). 각 CTE 정의(`AS ( ... )`)의
    본문은 괄호 깊이를 세어 건너뛴다 — 본문 안에 중첩된 서브쿼리/괄호가 있어도
    정확히 짝이 맞는 닫는 괄호에서 멈춘다. CTE 이름은 `WITH`/콤마 바로 뒤의 첫
    식별자(컬럼 목록 `(a, b)`가 있어도 `AS (`를 검색으로 찾으므로 영향 없음)로
    수집한다. 콤마로 이어지는 CTE가 더 없을 때까지 반복한다.
    """
    m = _WITH_START_PATTERN.match(q)
    if not m:
        return 0, frozenset()

    pos = m.end()
    n = len(q)
    names: set[str] = set()
    while True:
        while pos < n and q[pos].isspace():
            pos += 1
        name_match = _CTE_IDENTIFIER_PATTERN.match(q, pos)
        if not name_match:
            raise SqlGuardError("CTE 이름을 해석할 수 없습니다.")
        names.add(name_match.group(0).strip("[]\"").lower())

        as_match = _CTE_AS_OPEN_PATTERN.search(q, name_match.end())
        if not as_match:
            raise SqlGuardError("CTE 구문을 해석할 수 없습니다.")

        depth = 0
        i = as_match.end() - 1  # "(" 위치
        while i < n:
            if q[i] == "(":
                depth += 1
            elif q[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        else:
            raise SqlGuardError("CTE의 괄호 짝이 맞지 않습니다.")

        pos = i + 1
        while pos < n and q[pos].isspace():
            pos += 1

        if pos < n and q[pos] == ",":
            pos += 1
            while pos < n and q[pos].isspace():
                pos += 1
            continue

        break

    return pos, frozenset(names)


def validate_and_prepare(query: str) -> str:
    q = query.strip().rstrip(";")

    if ";" in q:
        raise SqlGuardError("다중 SQL 문장은 허용되지 않습니다.")

    is_cte = bool(_WITH_START_PATTERN.match(q))
    if not is_cte and not re.match(r"^\s*SELECT\b", q, re.IGNORECASE):
        raise SqlGuardError("SELECT 또는 WITH(CTE) 문만 허용됩니다.")

    if _FORBIDDEN_KEYWORDS.search(q):
        raise SqlGuardError("허용되지 않는 키워드가 포함되어 있습니다.")

    q = rewrite_query_with_aliases(q)

    # CTE 이름은 별칭 치환 이후의 최종 텍스트를 기준으로 파싱해야 오프셋이 맞는다.
    outer_start, cte_names = (
        _parse_cte_definitions(_mask_non_code(q)) if is_cte else (0, frozenset())
    )

    q = _check_and_qualify_table_refs(q, cte_names)

    # 위 치환(비수식 뷰 이름 → schema.view)으로 길이가 바뀔 수 있으므로,
    # outer_start를 치환 후 텍스트 기준으로 다시 계산한다.
    if is_cte:
        outer_start, _ = _parse_cte_definitions(_mask_non_code(q))
    outer_part = q[outer_start:]

    if not re.match(r"^\s*SELECT\b", outer_part, re.IGNORECASE):
        # CTE 정의는 전부 끝났는데 그 뒤가 SELECT가 아니면(예: 파싱이 어긋났거나
        # INSERT/UPDATE 등이 왔다면) 안전하게 거부한다. 정상적인 DML/DDL은 이미
        # _FORBIDDEN_KEYWORDS에서 걸러지지만, 방어적으로 한 번 더 확인한다.
        raise SqlGuardError("CTE 뒤에는 SELECT 문만 올 수 있습니다.")

    if not _TOP_PATTERN.match(outer_part):
        outer_part = _SELECT_PREFIX_PATTERN.sub(
            lambda m: f"{m.group(1)}SELECT{m.group(2)} TOP {MAX_ROWS} ",
            outer_part,
            count=1,
        )
        q = q[:outer_start] + outer_part

    return q
