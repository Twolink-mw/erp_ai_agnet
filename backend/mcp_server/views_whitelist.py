"""매출 관련 뷰 화이트리스트와 한글 별칭 매핑.

기본값은 "접근 불가"이며, 이 목록에 명시적으로 추가된
schema.view 형태의 뷰만 조회 대상이 된다.
"""

import re

# 실제 ERP 스키마에 맞춰 채워 넣는다. (예시)
SALES_VIEW_WHITELIST: set[str] = {
    "dbo.JINJU_SALES",
}

VIEW_ALIASES: dict[str, str] = {
    "매출": "dbo.JINJU_SALES",
}

COLUMN_ALIASES: dict[str, dict[str, str]] = {
    "dbo.JINJU_SALES": {
        "매출일": "SALES_DT",
        "제품군": "ITEM_GROUP",
        "제품류": "ITEM_TYPE",
        "제품명": "ITEM_NM",
        "바코드": "BARCODE",
        "레벨1": "LEVEL1",
        "레벨2": "LEVEL2",
        "레벨3": "LEVEL3",
        "거래처군": "CUST_LVL",
        "거래처,거래처명,고객": "CUST_NM",
        "관리사원,영업사원": "SALE_PRSN",
        "수량,매출수량,총수량": "SALES_QTY",
        "금액,매출금액,매출액,총금액": "SALES_AMT",
    }
}


def _normalize_name(value: str) -> str:
    return value.strip().lower()


def _parse_alias_keys(alias_key: str) -> list[str]:
    return [item.strip() for item in alias_key.split(",") if item.strip()]


VIEW_ALIAS_LOOKUP: dict[str, str] = {
    _normalize_name(alias): view_name
    for alias_key, view_name in VIEW_ALIASES.items()
    for alias in _parse_alias_keys(alias_key)
}

COLUMN_ALIAS_LOOKUP: dict[str, dict[str, str]] = {
    view_name: {
        _normalize_name(alias): column_name
        for alias_key, column_name in aliases.items()
        for alias in _parse_alias_keys(alias_key)
    }
    for view_name, aliases in COLUMN_ALIASES.items()
}


def resolve_view_name(alias_or_name: str) -> str | None:
    normalized = _normalize_name(alias_or_name)
    if normalized in VIEW_ALIAS_LOOKUP:
        return VIEW_ALIAS_LOOKUP[normalized]

    lowercase_whitelist = {v.lower(): v for v in SALES_VIEW_WHITELIST}
    return lowercase_whitelist.get(normalized)


def resolve_column_name(view_name: str, alias_or_name: str) -> str | None:
    canonical_view = resolve_view_name(view_name)
    if canonical_view is None:
        return None

    normalized = _normalize_name(alias_or_name)
    view_column_map = COLUMN_ALIAS_LOOKUP.get(canonical_view, {})
    if normalized in view_column_map:
        return view_column_map[normalized]

    for column_name in view_column_map.values():
        if column_name.lower() == normalized:
            return column_name

    return None


_STRING_LITERAL_PATTERN = re.compile(r"'(?:''|[^'])*'")
_VIEW_REF_PATTERN = re.compile(
    r"\b(FROM|JOIN)\s+([A-Za-z0-9_\uAC00-\uD7A3\.]+)\b",
    re.IGNORECASE,
)
_AS_SUFFIX_PATTERN = re.compile(r"\bAS\s*$", re.IGNORECASE)


def _build_column_alias_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for aliases in COLUMN_ALIAS_LOOKUP.values():
        for alias, column_name in aliases.items():
            lookup[alias] = column_name
    return lookup


ALL_COLUMN_ALIASES = _build_column_alias_lookup()


def _split_sql_by_strings(query: str) -> list[tuple[bool, str]]:
    parts: list[tuple[bool, str]] = []
    position = 0
    for match in _STRING_LITERAL_PATTERN.finditer(query):
        if position < match.start():
            parts.append((False, query[position : match.start()]))
        parts.append((True, match.group(0)))
        position = match.end()
    if position < len(query):
        parts.append((False, query[position:]))
    return parts


def _normalize_context_for_as_check(text: str) -> str:
    return text.strip().upper()


def rewrite_query_with_aliases(query: str) -> str:
    if not query:
        return query

    # 뷰 별칭을 실제 뷰명으로 변환
    def replace_view_reference(match: re.Match) -> str:
        keyword, view_token = match.group(1), match.group(2)
        canonical_view = resolve_view_name(view_token)
        if canonical_view and canonical_view.lower() != view_token.lower():
            return f"{keyword} {canonical_view}"
        return match.group(0)

    query = _VIEW_REF_PATTERN.sub(replace_view_reference, query)

    if not ALL_COLUMN_ALIASES:
        return query

    alias_pattern = re.compile(
        r"\b(" + r"|".join(re.escape(alias) for alias in sorted(ALL_COLUMN_ALIASES, key=len, reverse=True)) + r")\b",
        re.IGNORECASE,
    )

    def replace_column_alias(match: re.Match) -> str:
        alias_token = match.group(1)
        normalized = _normalize_name(alias_token)
        column_name = ALL_COLUMN_ALIASES.get(normalized)
        if not column_name:
            return alias_token

        prefix = query[max(0, match.start() - 10) : match.start()]
        if _AS_SUFFIX_PATTERN.search(prefix):
            return alias_token

        return column_name

    rewritten_parts: list[str] = []
    for is_string, segment in _split_sql_by_strings(query):
        if is_string:
            rewritten_parts.append(segment)
        else:
            rewritten_parts.append(alias_pattern.sub(replace_column_alias, segment))

    return "".join(rewritten_parts)


def get_view_aliases() -> list[dict[str, list[str]]]:
    return [
        {"view_name": view_name, "aliases": _parse_alias_keys(alias_key)}
        for alias_key, view_name in VIEW_ALIASES.items()
    ]


def get_column_aliases(view_name: str) -> list[dict[str, list[str]]]:
    canonical_view = resolve_view_name(view_name)
    if canonical_view is None:
        return []

    return [
        {"column_name": column_name, "aliases": _parse_alias_keys(alias_key)}
        for alias_key, column_name in COLUMN_ALIASES.get(canonical_view, {}).items()
    ]


def is_view_allowed(view_name: str) -> bool:
    return view_name.strip().lower() in {v.lower() for v in SALES_VIEW_WHITELIST}
