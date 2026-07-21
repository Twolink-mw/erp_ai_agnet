import pytest

from backend.mcp_server.views_whitelist import (
    get_column_aliases,
    get_view_aliases,
    is_view_allowed,
    resolve_column_name,
    resolve_view_name,
    rewrite_query_with_aliases,
)

VIEW = "dbo.JINJU_SALES"


class TestResolveViewName:
    def test_exact_schema_view_string_returned_as_is(self):
        assert resolve_view_name(VIEW) == VIEW

    def test_case_insensitive_schema_view_is_normalized(self):
        assert resolve_view_name("DBO.jinju_sales") == VIEW

    def test_registered_korean_alias_resolves(self):
        assert resolve_view_name("매출") == VIEW

    def test_unregistered_string_returns_none(self):
        assert resolve_view_name("dbo.NotAView") is None

    def test_whitespace_is_trimmed(self):
        assert resolve_view_name("  매출  ") == VIEW


class TestResolveColumnName:
    def test_registered_korean_column_alias_resolves(self):
        assert resolve_column_name(VIEW, "매출일") == "SALES_DT"

    @pytest.mark.parametrize("alias", ["매출수량", "수량", "총수량"])
    def test_grouped_aliases_map_to_same_column(self, alias):
        assert resolve_column_name(VIEW, alias) == "SALES_QTY"

    def test_unknown_view_returns_none(self):
        assert resolve_column_name("dbo.NotAView", "매출일") is None

    def test_known_view_unknown_column_alias_returns_none(self):
        assert resolve_column_name(VIEW, "존재하지않는별칭") is None

    def test_actual_column_name_case_insensitive_match(self):
        assert resolve_column_name(VIEW, "sales_amt") == "SALES_AMT"


class TestIsViewAllowed:
    def test_whitelisted_view_case_insensitive(self):
        assert is_view_allowed("DBO.JINJU_SALES") is True

    def test_non_whitelisted_view(self):
        assert is_view_allowed("dbo.Employee") is False


class TestRewriteQueryWithAliases:
    def test_from_korean_view_alias_rewritten(self):
        result = rewrite_query_with_aliases("SELECT * FROM 매출")
        assert f"FROM {VIEW}" in result

    def test_join_korean_view_alias_rewritten(self):
        result = rewrite_query_with_aliases("SELECT * FROM 매출 a JOIN 매출 b ON 1=1")
        assert result.count(VIEW) == 2

    def test_column_alias_in_select_and_where_rewritten(self):
        result = rewrite_query_with_aliases("SELECT 매출일 FROM 매출 WHERE 제품명 = 'x'")
        assert "SALES_DT" in result
        assert "ITEM_NM" in result

    def test_alias_text_inside_string_literal_not_rewritten(self):
        result = rewrite_query_with_aliases("SELECT * FROM 매출 WHERE CUST_NM = '거래처'")
        assert "'거래처'" in result

    def test_alias_after_as_keyword_not_rewritten(self):
        result = rewrite_query_with_aliases("SELECT SALES_DT AS 매출일 FROM 매출")
        assert "AS 매출일" in result

    def test_multiple_aliases_in_one_query_all_rewritten(self):
        result = rewrite_query_with_aliases(
            "SELECT 매출일, 제품명, 매출액 FROM 매출"
        )
        assert "SALES_DT" in result
        assert "ITEM_NM" in result
        assert "SALES_AMT" in result

    def test_unregistered_korean_text_left_unchanged(self):
        result = rewrite_query_with_aliases("SELECT * FROM 인사데이터")
        assert "인사데이터" in result

    def test_empty_string_returns_empty_string(self):
        assert rewrite_query_with_aliases("") == ""


class TestAliasIntrospection:
    def test_get_view_aliases_structure(self):
        aliases = get_view_aliases()
        assert any(a["view_name"] == VIEW and "매출" in a["aliases"] for a in aliases)

    def test_get_column_aliases_by_korean_view_alias(self):
        aliases = get_column_aliases("매출")
        names = {a["column_name"] for a in aliases}
        assert "SALES_DT" in names

    def test_get_column_aliases_unknown_view_returns_empty(self):
        assert get_column_aliases("dbo.NotAView") == []
