"""PDF 리포트 렌더링 계층 테스트.

핵심 계약:
1. /api/report/pdf는 application/pdf 바이너리를 반환한다.
2. 이 경로는 MCP/SQL을 전혀 건드리지 않는다 (순수 렌더링).
3. 깨진 chart 블록 등 비정상 입력에도 크래시하지 않는다.
4. ChatResponse의 report_available는 옵셔널이라 기존 계약을 깨지 않는다.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.pdf_report import (
    PdfReportRequest,
    _cell_markup,
    _strip_trailing_ui_action_hint,
    build_pdf,
    has_reportable_content,
    markdown_inline_to_rl,
    parse_markdown_blocks,
    safe_filename,
)

SAMPLE_REPLY = """\
# 2026년 상반기 매출 요약

상반기 총매출은 **12,340,000원**으로 전년 대비 8% 증가했습니다.

| 월 | 매출 | 건수 |
| --- | --- | --- |
| 1월 | 2,000,000 | 12 |
| 2월 | 2,340,000 | 15 |

- 2월이 최고 실적이었습니다.
- 제품 A가 매출의 60%를 차지합니다.

```chart
{"type": "line", "title": "월별 매출 추이", "xKey": "월",
 "series": [{"key": "매출", "name": "매출액"}],
 "data": [{"월": "1월", "매출": 2000000}, {"월": "2월", "매출": 2340000}]}
```
"""


@pytest.fixture
def client():
    return TestClient(main.app)


# --- 파서 ------------------------------------------------------------------


def test_parse_markdown_blocks_recognizes_all_block_kinds():
    kinds = [b["kind"] for b in parse_markdown_blocks(SAMPLE_REPLY)]
    assert "heading" in kinds
    assert "para" in kinds
    assert "table" in kinds
    assert "bullets" in kinds
    assert "chart" in kinds


def test_parse_markdown_table_header_and_rows():
    block = next(b for b in parse_markdown_blocks(SAMPLE_REPLY) if b["kind"] == "table")
    assert block["header"] == ["월", "매출", "건수"]
    assert block["rows"][0] == ["1월", "2,000,000", "12"]


def test_broken_chart_block_degrades_to_code_not_crash():
    blocks = parse_markdown_blocks("```chart\n{not json at all\n```")
    assert [b["kind"] for b in blocks] == ["code"]


def test_chart_block_failing_schema_degrades_to_code():
    # 유효한 JSON이지만 xKey가 없어 ReportChart 검증에 실패한다.
    blocks = parse_markdown_blocks('```chart\n{"type": "bar"}\n```')
    assert [b["kind"] for b in blocks] == ["code"]


def test_markdown_inline_escapes_xml_before_formatting():
    out = markdown_inline_to_rl("a < b & **강조** <script>")
    assert "&lt;" in out and "&amp;" in out
    assert "<b>강조</b>" in out
    assert "<script>" not in out


# --- report_available 힌트 --------------------------------------------------


def test_has_reportable_content_true_for_table_and_chart():
    assert has_reportable_content(SAMPLE_REPLY) is True
    assert has_reportable_content("```chart\n{}\n```") is True


def test_has_reportable_content_false_for_plain_text():
    assert has_reportable_content("안녕하세요, 무엇을 도와드릴까요?") is False


# --- 순위 변동(▲/▼) 셀 색상 ---------------------------------------------------


def test_cell_markup_colors_rank_up_red():
    out = _cell_markup("▲3")
    assert '<font color="#b4341c">' in out
    assert "▲3" in out


def test_cell_markup_colors_rank_down_blue():
    out = _cell_markup("▼12")
    assert '<font color="#1e5fb8">' in out
    assert "▼12" in out


@pytest.mark.parametrize("value", ["-", "신규", "123", "▲", "▲3위", " ▲3 상승"])
def test_cell_markup_leaves_non_matching_values_uncolored(value):
    out = _cell_markup(value)
    assert "<font color=" not in out


def test_cell_markup_handles_surrounding_whitespace():
    # 셀 값 앞뒤 공백은 정상적으로 화살표+숫자 판정에서 무시된다.
    out = _cell_markup("  ▲7  ")
    assert '<font color="#b4341c">' in out


# --- PDF 전용 UI 안내 문구 제거 ----------------------------------------------


def test_strip_trailing_ui_hint_removes_pdf_download_sentence():
    content = "# 리포트\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\n아래 PDF 다운로드 버튼으로 저장할 수 있습니다."
    cleaned = _strip_trailing_ui_action_hint(content)
    assert "PDF 다운로드 버튼" not in cleaned
    assert "| a | b |" in cleaned


def test_strip_trailing_ui_hint_removes_email_send_sentence():
    content = "# 리포트\n\n요약 내용입니다.\n\n아래 이메일 발송 버튼으로 전달할 수 있습니다."
    cleaned = _strip_trailing_ui_action_hint(content)
    assert "이메일 발송 버튼" not in cleaned
    assert "요약 내용입니다." in cleaned


def test_strip_trailing_ui_hint_also_removes_preceding_horizontal_rule():
    # 모델이 안내 문구 앞에 마크다운 구분선(---)을 붙이는 경우도 함께 제거된다.
    content = "요약 내용입니다.\n\n---\n아래 PDF 다운로드 버튼으로 저장할 수 있습니다."
    cleaned = _strip_trailing_ui_action_hint(content)
    assert "PDF 다운로드 버튼" not in cleaned
    assert "---" not in cleaned
    assert cleaned.strip() == "요약 내용입니다."


def test_strip_trailing_ui_hint_leaves_content_without_hint_untouched():
    content = "# 리포트\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n"
    assert _strip_trailing_ui_action_hint(content) == content


def test_strip_trailing_ui_hint_does_not_remove_mid_document_mention():
    # 안내 문구와 같은 표현이 우연히 본문 중간에 나오고 뒤에 실질 내용이 더
    # 있으면(=응답 맨 끝이 아니면) 건드리지 않는다.
    content = "아래 PDF 다운로드 버튼으로 저장할 수 있습니다.\n\n추가 설명입니다."
    assert _strip_trailing_ui_action_hint(content) == content


def test_build_pdf_excludes_ui_download_hint_text():
    content = (
        "# 2026년 8월 매출 요약\n\n"
        "| 항목 | 값 |\n| --- | --- |\n| 총매출 | 100 |\n\n"
        "아래 PDF 다운로드 버튼으로 저장할 수 있습니다."
    )
    req = PdfReportRequest(title="매출 리포트", content=content)
    data = build_pdf(req)
    assert data.startswith(b"%PDF-")

    # reportlab이 생성하는 PDF는 텍스트를 압축된 콘텐츠 스트림에 담으므로 원문
    # 바이트를 직접 검색할 수 없다 — 대신 build_pdf가 실제로 사용하는 것과 동일한
    # 파싱 경로(안내 문구 제거 → 마크다운 파싱)로 어떤 블록이 PDF에 들어갔을지
    # 검증한다. 표/제목은 살아있고, 안내 문구를 담은 문단은 없어야 한다.
    blocks = parse_markdown_blocks(_strip_trailing_ui_action_hint(content))
    assert any(b["kind"] == "table" for b in blocks)
    assert not any(
        b["kind"] == "para" and "PDF 다운로드 버튼" in b["text"] for b in blocks
    )
    assert has_reportable_content("") is False


# --- 파일명 ----------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["../../etc/passwd", "report\\..\\x", "  ", None, "매출리포트"],
)
def test_safe_filename_has_no_path_separators_and_pdf_suffix(raw):
    name = safe_filename(raw)
    assert "/" not in name and "\\" not in name and ".." not in name
    assert name.endswith(".pdf")


# --- PDF 빌드 ---------------------------------------------------------------


def test_build_pdf_returns_pdf_bytes():
    data = build_pdf(PdfReportRequest(title="매출 리포트", content=SAMPLE_REPLY))
    assert data.startswith(b"%PDF-")
    assert len(data) > 1000


def test_build_pdf_handles_empty_content():
    data = build_pdf(PdfReportRequest())
    assert data.startswith(b"%PDF-")


def test_build_pdf_accepts_explicit_tables_and_charts():
    req = PdfReportRequest(
        title="명시 표/차트",
        content="",
        tables=[{"title": "월별", "columns": ["월", "매출"], "rows": [["1월", 2000000]]}],
        charts=[
            {
                "type": "bar",
                "title": "제품별",
                "xKey": "제품",
                "series": [{"key": "매출", "name": "매출액"}],
                "data": [{"제품": "A", "매출": 100}, {"제품": "B", "매출": 200}],
            }
        ],
    )
    assert build_pdf(req).startswith(b"%PDF-")


def test_build_pdf_renders_table_with_rank_change_cells_without_crashing():
    content = (
        "| 순위 | 제품 | 매출 | 변동 |\n"
        "| --- | --- | --- | --- |\n"
        "| 1 | A | 100 | ▲3 |\n"
        "| 2 | B | 90 | ▼12 |\n"
        "| 3 | C | 80 | - |\n"
    )
    data = build_pdf(PdfReportRequest(title="순위 변동", content=content))
    assert data.startswith(b"%PDF-")


def test_build_pdf_handles_ragged_table_rows():
    req = PdfReportRequest(
        content="| a | b | c |\n| --- | --- | --- |\n| 1 |\n| 1 | 2 | 3 |\n"
    )
    assert build_pdf(req).startswith(b"%PDF-")


# --- 엔드포인트 -------------------------------------------------------------


def test_report_pdf_endpoint_returns_pdf_stream(client):
    res = client.post(
        "/api/report/pdf",
        json={"title": "매출 리포트", "question": "상반기 매출은?", "content": SAMPLE_REPLY},
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert "attachment" in res.headers["content-disposition"]
    assert res.content.startswith(b"%PDF-")


def test_report_pdf_endpoint_accepts_minimal_body(client):
    res = client.post("/api/report/pdf", json={"content": "매출 요약입니다."})
    assert res.status_code == 200
    assert res.content.startswith(b"%PDF-")


def test_report_pdf_endpoint_does_not_touch_mcp(client, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("PDF 엔드포인트가 MCP 세션을 열어서는 안 된다")

    monkeypatch.setattr(main, "run_chat", boom)
    res = client.post("/api/report/pdf", json={"content": SAMPLE_REPLY})
    assert res.status_code == 200


def test_chat_response_includes_report_available_flag(client, monkeypatch):
    async def fake_run_chat(messages):
        return {"reply": SAMPLE_REPLY, "tool_calls": []}

    monkeypatch.setattr(main, "run_chat", fake_run_chat)
    body = client.post("/api/chat", json={"messages": []}).json()
    assert body["report_available"] is True


def test_chat_response_report_available_false_for_plain_reply(client, monkeypatch):
    async def fake_run_chat(messages):
        return {"reply": "안녕하세요", "tool_calls": []}

    monkeypatch.setattr(main, "run_chat", fake_run_chat)
    body = client.post("/api/chat", json={"messages": []}).json()
    assert body["report_available"] is False
