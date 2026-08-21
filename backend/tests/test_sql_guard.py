import re

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

    def test_distinct_without_top_gets_top_after_distinct(self):
        # T-SQL: SELECT [ALL|DISTINCT] [TOP n] — TOP은 DISTINCT 뒤에 와야 한다.
        q = f"SELECT DISTINCT SALES_DT FROM {VIEW}"
        result = validate_and_prepare(q)
        assert result.upper().count("TOP") == 1
        assert re.match(r"^\s*SELECT\s+DISTINCT\s+TOP\s+1000\s+SALES_DT\b", result, re.IGNORECASE)
        # 회귀: TOP이 DISTINCT 앞에 삽입되면 문법 오류(156)가 난다.
        assert "TOP 1000 DISTINCT" not in result.upper()

    def test_distinct_with_existing_top_is_not_duplicated(self):
        q = f"SELECT DISTINCT TOP 10 SALES_DT FROM {VIEW} ORDER BY SALES_DT"
        result = validate_and_prepare(q)
        assert result.upper().count("TOP") == 1
        assert "TOP 10" in result

    def test_distinct_with_existing_parenthesized_top_is_not_duplicated(self):
        q = f"SELECT DISTINCT TOP (25) SALES_DT FROM {VIEW}"
        result = validate_and_prepare(q)
        assert result.upper().count("TOP") == 1
        assert "TOP (25)" in result

    @pytest.mark.parametrize(
        "prefix",
        ["SELECT DISTINCT", "select distinct", "SeLeCt DiStInCt", "SELECT   DISTINCT", "SELECT\nDISTINCT"],
    )
    def test_distinct_case_and_whitespace_variants(self, prefix):
        result = validate_and_prepare(f"{prefix} SALES_DT FROM {VIEW}")
        assert result.upper().count("TOP") == 1
        assert re.search(r"DISTINCT\s+TOP\s+1000\b", result, re.IGNORECASE)
        assert "TOP 1000 DISTINCT" not in result.upper()

    def test_distinct_immediately_followed_by_paren_stays_valid(self):
        q = f"SELECT DISTINCT(SALES_DT) FROM {VIEW}"
        result = validate_and_prepare(q)
        assert re.search(r"DISTINCT\s+TOP\s+1000\s+\(SALES_DT\)", result, re.IGNORECASE)

    def test_select_all_qualifier_gets_top_after_all(self):
        q = f"SELECT ALL SALES_DT FROM {VIEW}"
        result = validate_and_prepare(q)
        assert result.upper().count("TOP") == 1
        assert re.match(r"^\s*SELECT\s+ALL\s+TOP\s+1000\b", result, re.IGNORECASE)

    def test_column_starting_with_distinct_prefix_is_not_treated_as_qualifier(self):
        # `DISTINCTIVE`는 한정자가 아니므로 TOP은 SELECT 바로 뒤에 삽입돼야 한다.
        q = f"SELECT DISTINCTIVE_FLAG FROM {VIEW}"
        result = validate_and_prepare(q)
        assert re.match(r"^\s*SELECT\s+TOP\s+1000\s+DISTINCTIVE_FLAG\b", result, re.IGNORECASE)

    def test_distinct_query_survives_alias_rewrite(self):
        # 별칭 치환(한글) → 키워드 검사 → 테이블 검사 → TOP 삽입 순서가 유지되는지.
        result = validate_and_prepare("SELECT DISTINCT 거래처 FROM 매출")
        assert "CUST_NM" in result
        assert VIEW in result
        assert re.search(r"DISTINCT\s+TOP\s+1000\s+CUST_NM", result, re.IGNORECASE)

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
        # "WITH ..."는 더 이상 이 목록에 없다 — CTE는 이제 정식으로 허용되며
        # TestCteQueries에서 별도로 검증한다.
        ["EXEC sp_who", "UPDATE dbo.X SET a=1"],
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


class TestUnqualifiedTableReferences:
    """비수식(unqualified) 테이블명 우회에 대한 회귀 테스트.

    이전 `_TABLE_REF_PATTERN`은 `schema.name` 형태만 캡처했기 때문에,
    화이트리스트 뷰가 하나라도 함께 참조되면 `FROM SecretTable` 같은
    비수식 참조가 검사되지 않고 통과했다. MSSQL은 비수식 이름을 실행 계정의
    기본 스키마로 해석하므로 실제로 도달 가능한 취약점이었다.
    """

    @pytest.mark.parametrize(
        "query",
        [
            f"SELECT * FROM {VIEW} UNION SELECT * FROM SecretTable",
            f"SELECT * FROM {VIEW} a JOIN SecretTable b ON 1=1",
            f"SELECT * FROM {VIEW} WHERE 1 IN (SELECT 1 FROM SecretTable)",
        ],
    )
    def test_unqualified_table_alongside_whitelisted_view_blocked(self, query):
        with pytest.raises(SqlGuardError, match="허용된 매출 뷰 목록"):
            validate_and_prepare(query)

    def test_unqualified_table_in_comma_separated_from_list_blocked(self):
        q = f"SELECT * FROM {VIEW}, SecretTable"
        with pytest.raises(SqlGuardError, match="허용된 매출 뷰 목록"):
            validate_and_prepare(q)

    def test_qualified_table_in_comma_separated_from_list_blocked(self):
        q = f"SELECT * FROM {VIEW}, dbo.Employee"
        with pytest.raises(SqlGuardError, match="허용된 매출 뷰 목록"):
            validate_and_prepare(q)

    def test_unqualified_table_alone_blocked(self):
        with pytest.raises(SqlGuardError):
            validate_and_prepare("SELECT * FROM SecretTable")

    @pytest.mark.parametrize("token", ["@tablevar", "#temp"])
    def test_table_variable_and_temp_table_blocked(self, token):
        with pytest.raises(SqlGuardError):
            validate_and_prepare(f"SELECT * FROM {VIEW} UNION SELECT * FROM {token}")

    def test_three_part_cross_database_reference_blocked(self):
        with pytest.raises(SqlGuardError, match="3부분 이상"):
            validate_and_prepare(f"SELECT * FROM otherdb.{VIEW}")

    def test_unqualified_whitelisted_view_is_allowed_and_schema_qualified(self):
        # 기본 스키마 해석의 모호성을 없애기 위해 통과한 비수식 참조는
        # 실행 SQL에서 schema.view 형태로 수식되어야 한다.
        result = validate_and_prepare("SELECT SALES_AMT FROM JINJU_SALES")
        assert VIEW in result

    def test_derived_table_with_whitelisted_view_allowed(self):
        result = validate_and_prepare(f"SELECT * FROM (SELECT * FROM {VIEW}) t")
        assert VIEW in result

    def test_with_nolock_hint_allowed(self):
        result = validate_and_prepare(f"SELECT * FROM {VIEW} WITH (NOLOCK)")
        assert VIEW in result

    def test_bracketed_identifier_containing_dot_blocked(self):
        # [dbo.JINJU_SALES]는 schema.view 2부분 참조가 아니라 이름에 점이 든
        # 단일 식별자다. 화이트리스트와 대응시킬 수 없으므로 거부한다.
        with pytest.raises(SqlGuardError, match="해석할 수 없는"):
            validate_and_prepare("SELECT * FROM [dbo.JINJU_SALES]")


class TestApplyOperator:
    """CROSS/OUTER APPLY 우변도 FROM/JOIN과 동일한 table_source이므로 검사 대상이다."""

    @pytest.mark.parametrize(
        "query",
        [
            f"SELECT * FROM {VIEW} a CROSS APPLY HR.Payroll p",
            f"SELECT * FROM {VIEW} a CROSS APPLY dbo.Employee b",
            f"SELECT * FROM {VIEW} a CROSS APPLY SecretTable b",
            f"SELECT * FROM {VIEW} a OUTER APPLY dbo.SecretFn(a.BARCODE) b",
            f"SELECT * FROM {VIEW} a OUTER APPLY (SELECT * FROM SecretTable) b",
        ],
    )
    def test_apply_to_non_whitelisted_target_blocked(self, query):
        with pytest.raises(SqlGuardError):
            validate_and_prepare(query)

    def test_apply_does_not_break_preceding_from_segment(self):
        q = f"SELECT * FROM {VIEW} a CROSS APPLY (SELECT 1 AS x) b"
        result = validate_and_prepare(q)
        assert VIEW in result


class TestLiteralAndCommentMasking:
    """리터럴/주석 안의 FROM·JOIN이 테이블 참조로 오인되면 안 된다(오탐 방지)."""

    @pytest.mark.parametrize(
        "query",
        [
            f"SELECT * FROM {VIEW} WHERE CUST_NM = 'JOIN Corp'",
            f"SELECT * FROM {VIEW} WHERE CUST_NM LIKE '%from%'",
            f"SELECT * FROM {VIEW} WHERE ITEM_NM = '어떤 from 상품'",
            f"SELECT * FROM {VIEW} -- from SecretTable",
            f"SELECT * FROM {VIEW} /* join SecretTable */",
        ],
    )
    def test_from_join_inside_literal_or_comment_is_not_a_table_ref(self, query):
        result = validate_and_prepare(query)
        assert VIEW in result

    def test_masking_does_not_hide_a_real_table_ref(self):
        # 주석을 마스킹해도 그 뒤의 실제 참조는 정상적으로 잡혀 차단되어야 한다.
        q = f"SELECT * FROM {VIEW} /*x*/ JOIN /*y*/ SecretTable b ON 1=1"
        with pytest.raises(SqlGuardError, match="허용된 매출 뷰 목록"):
            validate_and_prepare(q)

    def test_quote_inside_bracketed_identifier_does_not_desync_masking(self):
        q = f"SELECT * FROM {VIEW} a JOIN [we'ird] b ON 1=1"
        with pytest.raises(SqlGuardError):
            validate_and_prepare(q)


class TestSelectInto:
    def test_select_into_blocked(self):
        # SELECT처럼 보이지만 테이블을 생성하는 쓰기 작업이다.
        with pytest.raises(SqlGuardError, match="허용되지 않는 키워드"):
            validate_and_prepare(f"SELECT * INTO SecretCopy FROM {VIEW}")


class TestCteQueries:
    """WITH ... AS (...) SELECT ... (CTE) 지원에 대한 테스트.

    이전 달 대비 순위 변동처럼 다단계 집계가 필요한 질문에서 Gemini가 CTE를
    즐겨 쓰는데, 과거에는 "SELECT 문만 허용됩니다"로 전부 거부되어 불필요한
    재시도(및 그로 인한 타임아웃)를 유발했다. CTE를 허용하되 화이트리스트/금지
    키워드/다중 문장 차단은 동일하게 유지되는지, TOP이 CTE 정의 안이 아니라
    바깥쪽 최종 SELECT에 정확히 삽입되는지가 핵심 검증 대상이다.
    """

    def test_basic_cte_passes_and_top_inserted_on_outer_select_only(self):
        q = (
            f"WITH ranked AS ("
            f"SELECT ITEM_NM, SUM(SALES_AMT) AS TotalSales FROM {VIEW} GROUP BY ITEM_NM"
            f") SELECT ITEM_NM, TotalSales FROM ranked ORDER BY TotalSales DESC"
        )
        result = validate_and_prepare(q)
        assert VIEW in result
        assert result.upper().count("TOP") == 1
        # TOP은 CTE 정의 안의 SELECT가 아니라 바깥쪽(마지막) SELECT에 있어야 한다.
        outer_select_index = result.upper().rindex("SELECT")
        assert "TOP 1000" in result[outer_select_index:].upper()
        assert "TOP" not in result[:outer_select_index].upper()

    def test_multiple_comma_separated_ctes_pass(self):
        q = (
            f"WITH august AS ("
            f"SELECT ITEM_NM, SUM(SALES_AMT) AS s FROM {VIEW} WHERE SALES_DT = '2026-08' GROUP BY ITEM_NM"
            f"), july AS ("
            f"SELECT ITEM_NM, SUM(SALES_AMT) AS s FROM {VIEW} WHERE SALES_DT = '2026-07' GROUP BY ITEM_NM"
            f") SELECT august.ITEM_NM, august.s, july.s "
            f"FROM august JOIN july ON august.ITEM_NM = july.ITEM_NM"
        )
        result = validate_and_prepare(q)
        assert result.upper().count("TOP") == 1

    def test_existing_outer_top_is_not_duplicated(self):
        q = (
            f"WITH ranked AS ("
            f"SELECT ITEM_NM, SUM(SALES_AMT) AS s FROM {VIEW} GROUP BY ITEM_NM"
            f") SELECT TOP 5 ITEM_NM, s FROM ranked ORDER BY s DESC"
        )
        result = validate_and_prepare(q)
        assert result.upper().count("TOP") == 1
        assert "TOP 5" in result

    def test_top_only_inside_cte_body_still_gets_outer_top_added(self):
        # CTE 본문의 TOP은 CTE 자체의 결과만 제한할 뿐, 바깥쪽 최종 결과 집합은
        # 별도로 제한되지 않으므로 바깥쪽에도 TOP이 추가돼야 한다.
        q = (
            f"WITH ranked AS ("
            f"SELECT TOP 5 ITEM_NM, SUM(SALES_AMT) AS s FROM {VIEW} GROUP BY ITEM_NM"
            f") SELECT ITEM_NM, s FROM ranked"
        )
        result = validate_and_prepare(q)
        assert result.upper().count("TOP") == 2
        outer_select_index = result.upper().rindex("SELECT")
        assert "TOP 1000" in result[outer_select_index:].upper()

    @pytest.mark.parametrize("prefix", ["with ", "With ", "WITH ", "  WITH  ", "WITH\n"])
    def test_with_keyword_case_and_whitespace_variants_recognized(self, prefix):
        q = f"{prefix}x AS (SELECT ITEM_NM FROM {VIEW}) SELECT * FROM x"
        result = validate_and_prepare(q)
        assert VIEW in result

    def test_non_whitelisted_table_inside_cte_body_blocked(self):
        q = f"WITH x AS (SELECT * FROM SecretTable) SELECT * FROM x"
        with pytest.raises(SqlGuardError, match="허용된 매출 뷰 목록"):
            validate_and_prepare(q)

    def test_non_whitelisted_table_in_outer_query_blocked(self):
        q = (
            f"WITH x AS (SELECT ITEM_NM FROM {VIEW}) "
            f"SELECT * FROM x JOIN SecretTable y ON 1=1"
        )
        with pytest.raises(SqlGuardError, match="허용된 매출 뷰 목록"):
            validate_and_prepare(q)

    def test_semicolon_injection_after_cte_still_blocked(self):
        q = f"WITH x AS (SELECT 1) SELECT * FROM {VIEW}; DROP TABLE {VIEW}"
        with pytest.raises(SqlGuardError):
            validate_and_prepare(q)

    def test_forbidden_keyword_hidden_inside_cte_body_blocked(self):
        q = f"WITH x AS (INSERT INTO {VIEW} DEFAULT VALUES) SELECT * FROM x"
        with pytest.raises(SqlGuardError, match="허용되지 않는 키워드"):
            validate_and_prepare(q)

    def test_cte_with_no_outer_select_blocked(self):
        # CTE 정의만 있고 그 뒤에 최종 SELECT가 없는(불완전한) 쿼리는 거부돼야 한다.
        q = f"WITH x AS (SELECT * FROM {VIEW})"
        with pytest.raises(SqlGuardError, match="CTE 뒤에는 SELECT"):
            validate_and_prepare(q)

    def test_cte_survives_korean_alias_rewrite(self):
        q = "WITH ranked AS (SELECT 거래처, 매출액 FROM 매출) SELECT * FROM ranked"
        result = validate_and_prepare(q)
        assert VIEW in result
        assert "CUST_NM" in result
        assert "SALES_AMT" in result

    def test_non_cte_queries_unaffected(self):
        # 회귀: WITH가 아닌 일반 SELECT 경로는 기존과 동일하게 동작해야 한다.
        result = validate_and_prepare(f"SELECT SALES_AMT FROM {VIEW}")
        assert result.upper().startswith("SELECT TOP 1000")
