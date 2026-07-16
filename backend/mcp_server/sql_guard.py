"""LLM이 생성한 SQL을 실행 전에 검증하는 가드레일.

원칙:
- SELECT 단일 문장만 허용 (세미콜론으로 이어진 다중 문장 금지)
- FROM/JOIN 대상은 화이트리스트에 등록된 뷰만 허용
- DDL/DML 및 위험 키워드/시스템 프로시저 호출 금지
- 결과 행수 상한 강제 (TOP 절 누락 시 자동 삽입)
"""

import re

from .views_whitelist import SALES_VIEW_WHITELIST, is_view_allowed, rewrite_query_with_aliases

MAX_ROWS = 1000

_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|MERGE|TRUNCATE|CREATE|EXEC|EXECUTE|"
    r"GRANT|REVOKE|xp_cmdshell|sp_executesql|OPENROWSET|OPENQUERY|OPENDATASOURCE)\b",
    re.IGNORECASE,
)

_TABLE_REF_PATTERN = re.compile(
    r"\b(?:FROM|JOIN)\s+\[?([A-Za-z0-9_]+)\]?\.\[?([A-Za-z0-9_]+)\]?", re.IGNORECASE
)

_TOP_PATTERN = re.compile(r"^\s*SELECT\s+TOP\s*\(?\s*\d+\s*\)?", re.IGNORECASE)


class SqlGuardError(ValueError):
    pass


def validate_and_prepare(query: str) -> str:
    q = query.strip().rstrip(";")

    if ";" in q:
        raise SqlGuardError("다중 SQL 문장은 허용되지 않습니다.")

    if not re.match(r"^\s*SELECT\b", q, re.IGNORECASE):
        raise SqlGuardError("SELECT 문만 허용됩니다.")

    if _FORBIDDEN_KEYWORDS.search(q):
        raise SqlGuardError("허용되지 않는 키워드가 포함되어 있습니다.")

    q = rewrite_query_with_aliases(q)

    referenced = _TABLE_REF_PATTERN.findall(q)
    if not referenced:
        raise SqlGuardError("FROM 절에서 대상 뷰를 확인할 수 없습니다.")

    for schema, name in referenced:
        view_name = f"{schema}.{name}"
        if not is_view_allowed(view_name):
            raise SqlGuardError(
                f"'{view_name}' 은(는) 허용된 매출 뷰 목록에 없습니다. "
                f"허용된 뷰: {', '.join(sorted(SALES_VIEW_WHITELIST))}"
            )

    if not _TOP_PATTERN.match(q):
        q = re.sub(r"^\s*SELECT\b", f"SELECT TOP {MAX_ROWS}", q, count=1, flags=re.IGNORECASE)

    return q
