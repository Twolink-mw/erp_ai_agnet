"""공통 fixture.

sql_guard/views_whitelist는 실제 화이트리스트(dbo.JINJU_SALES)를 그대로 대상으로
테스트한다 — 화이트리스트 내용을 mock으로 치환하면 "실제 운영 설정에서 가드가
작동하는가"를 검증하지 못하게 되기 때문이다.
"""

import pytest


@pytest.fixture
def allowed_view() -> str:
    return "dbo.JINJU_SALES"
