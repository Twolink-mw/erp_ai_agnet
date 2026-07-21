import pytest

from backend.mcp_server.sql_guard import SqlGuardError, validate_and_prepare

VIEW = "dbo.JINJU_SALES"

FORBIDDEN_KEYWORDS = [
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "MERGE",
    "TRUNCATE",
    "CREATE",
    "EXEC",
    "EXECUTE",
    "GRANT",
    "REVOKE",
    "xp_cmdshell",
    "sp_executesql",
    "OPENROWSET",
    "OPENQUERY",
    "OPENDATASOURCE",
]


class TestNormalQueries:
    def test_simple_select_on_whitelisted_view_passes(self):
        q = f"SELECT SALES_AMT FROM {VIEW}"
        result = validate_and_prepare(q)
        assert VIEW in result

    def test_missing_top_gets_auto_inserted(self):
        q = f"SELECT SALES_AMT FROM {VIEW}"
        result = validate_and_prepare(q)
        assert result.upper().startswith("SELECT TOP 1000")

    def test_existing_top_is_not_duplicated(self):
        q = f"SELECT TOP 50 SALES_AMT FROM {VIEW}"
        result = validate_and_prepare(q)
        assert result.upper().count("TOP") == 1
        assert "TOP 50" in result

    def test_existing_top_with_parens_is_not_duplicated(self):
        q = f"SELECT TOP (100) SALES_AMT FROM {VIEW}"
        result = validate_and_prepare(q)
        assert result.upper().count("TOP") == 1

    def test_trailing_semicolon_is_stripped_and_allowed(self):
        q = f"SELECT SALES_AMT FROM {VIEW};"
        result = validate_and_prepare(q)
        assert ";" not in result

    def test_join_between_two_references_of_whitelisted_view_passes(self):
        q = (
            f"SELECT a.SALES_AMT FROM {VIEW} a "
            f"JOIN {VIEW} b ON a.SALES_DT = b.SALES_DT"
        )
        result = validate_and_prepare(q)
        assert result

    def test_mixed_case_keywords_are_recognized(self):
        q = f"select SALES_AMT From {VIEW}"
        result = validate_and_prepare(q)
        assert result


class TestBlockedQueries:
    def test_multiple_statements_blocked(self):
        with pytest.raises(SqlGuardError):
            validate_and_prepare(f"SELECT SALES_AMT FROM {VIEW}; DROP TABLE {VIEW}")

    @pytest.mark.parametrize(
        "prefix",
        ["WITH cte AS (SELECT 1)", "EXEC sp_who", "UPDATE dbo.X SET a=1"],
    )
    def test_non_select_statements_blocked(self, prefix):
        with pytest.raises(SqlGuardError):
            validate_and_prepare(prefix)

    @pytest.mark.parametrize("keyword", FORBIDDEN_KEYWORDS)
    def test_forbidden_keywords_blocked(self, keyword):
        q = f"SELECT SALES_AMT FROM {VIEW} WHERE 1=1 {keyword} dummy"
        with pytest.raises(SqlGuardError):
            validate_and_prepare(q)

    def test_forbidden_keyword_inside_string_literal_is_still_blocked(self):
        # sql_guard의 금지어 검사는 별칭 치환 이전, 문자열 여부를 구분하지 않고
        # 원문 전체에 대해 수행된다 — 즉 문자열 리터럴 안의 금지어도 차단된다.
        # 이는 오탐(false positive)이지만 "덜 허용" 방향의 실패이므로 현재 설계상
        # 허용된 동작으로 간주하고 회귀 테스트로 고정한다.
        q = f"SELECT SALES_AMT FROM {VIEW} WHERE ITEM_NM = 'please DELETE me'"
        with pytest.raises(SqlGuardError):
            validate_and_prepare(q)

    def test_no_from_or_join_blocked(self):
        with pytest.raises(SqlGuardError):
            validate_and_prepare("SELECT 1")

    @pytest.mark.parametrize(
        "target",
        ["dbo.Employee", "hr.Salary", "dbo.PayrollDetail"],
    )
    def test_non_whitelisted_view_blocked(self, target):
        with pytest.raises(SqlGuardError, match="허용된 매출 뷰 목록"):
            validate_and_prepare(f"SELECT * FROM {target}")

    def test_whitelisted_plus_non_whitelisted_join_blocked(self):
        q = f"SELECT a.SALES_AMT FROM {VIEW} a JOIN dbo.Employee b ON a.SALE_PRSN = b.ID"
        with pytest.raises(SqlGuardError):
            validate_and_prepare(q)

    def test_bracketed_view_reference_is_recognized_and_allowed(self):
        q = f"SELECT SALES_AMT FROM [dbo].[JINJU_SALES]"
        result = validate_and_prepare(q)
        assert result


class TestBypassAttempts:
    def test_sql_comment_after_semicolon_still_blocked_by_semicolon_check(self):
        q = f"SELECT SALES_AMT FROM {VIEW}; -- DROP TABLE {VIEW}"
        with pytest.raises(SqlGuardError):
            validate_and_prepare(q)

    def test_mixed_case_execute_keyword_blocked(self):
        q = f"SELECT SALES_AMT FROM {VIEW} WHERE 1=1; ExEcUtE ('x')"
        with pytest.raises(SqlGuardError):
            validate_and_prepare(q)

    def test_unregistered_korean_text_as_view_is_not_rewritten_and_gets_blocked(self):
        # "매출"은 별칭 테이블에 등록되어 있지만, 등록되지 않은 임의의 한글 문자열은
        # rewrite_query_with_aliases에서 치환되지 않고 원문 그대로 남아 whitelist
        # 검사 단계에서 차단되어야 한다.
        q = "SELECT * FROM 인사데이터"
        with pytest.raises(SqlGuardError):
            validate_and_prepare(q)

    def test_registered_korean_alias_is_rewritten_and_allowed(self):
        q = "SELECT 매출액 FROM 매출"
        result = validate_and_prepare(q)
        assert VIEW in result
        assert "SALES_AMT" in result
