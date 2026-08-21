"""챗봇이 이미 반환한 매출 조회 결과 → PDF 리포트 렌더링.

**이 모듈은 순수 렌더링 계층이다.** DB/MCP/SQL에 전혀 접근하지 않는다.
프론트엔드가 화면에서 이미 받은 챗봇 응답 텍스트(마크다운 + ```chart 블록)와
선택적 표/차트 데이터를 받아 PDF 바이트로 변환할 뿐이므로,
views_whitelist / sql_guard 등 보안 가드 경로와는 완전히 분리되어 있다.
새 데이터를 조회해야 하는 기능을 여기에 추가하지 말 것 — 그런 요청은
반드시 MCP 도구(run_sql)와 가드를 거치는 /api/chat 경로로 가야 한다.

한글 렌더링은 reportlab에 내장된 Adobe CID 폰트(HYSMyeongJo-Medium /
HYGothic-Medium)를 사용한다 — 외부 TTF 파일을 배포할 필요가 없다.
등록에 실패하면 Helvetica로 폴백해 최소한 PDF 생성 자체는 성공시킨다.
"""

from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ---------------------------------------------------------------------------
# 요청/응답 스키마
# ---------------------------------------------------------------------------


class ReportTable(BaseModel):
    """명시적으로 전달하는 표. content 안의 마크다운 표와 별개로 추가된다."""

    title: str | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)


class ReportSeries(BaseModel):
    key: str
    name: str | None = None


class ReportChart(BaseModel):
    """프론트 ChartRenderer가 쓰는 ```chart 블록과 동일한 스키마."""

    type: Literal["bar", "line"] = "bar"
    title: str | None = None
    xKey: str
    series: list[ReportSeries] = Field(default_factory=list)
    data: list[dict[str, Any]] = Field(default_factory=list)


class PdfReportRequest(BaseModel):
    title: str | None = None
    question: str | None = None
    content: str = ""
    tables: list[ReportTable] = Field(default_factory=list)
    charts: list[ReportChart] = Field(default_factory=list)
    generated_at: str | None = None
    filename: str | None = None


DEFAULT_TITLE = "ERP 매출 분석 리포트"

# ChartRenderer.tsx의 라이트 테마 팔레트와 동일한 순서
SERIES_COLORS = [
    colors.HexColor("#2a78d6"),
    colors.HexColor("#1baf7a"),
    colors.HexColor("#eda100"),
    colors.HexColor("#008300"),
    colors.HexColor("#4a3aa7"),
    colors.HexColor("#e34948"),
    colors.HexColor("#e87ba4"),
    colors.HexColor("#eb6834"),
]

_FONTS_READY = False
BODY_FONT = "Helvetica"
BOLD_FONT = "Helvetica-Bold"
MONO_FONT = "Courier"


def _ensure_fonts() -> tuple[str, str]:
    """한글 CID 폰트를 1회 등록하고 (본문, 강조) 폰트 이름을 돌려준다."""
    global _FONTS_READY, BODY_FONT, BOLD_FONT
    if _FONTS_READY:
        return BODY_FONT, BOLD_FONT
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
        pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))
        BODY_FONT = "HYSMyeongJo-Medium"
        BOLD_FONT = "HYGothic-Medium"
    except Exception:
        # 폰트 등록 실패는 치명적이지 않다 — 한글이 깨지더라도 PDF는 생성한다.
        BODY_FONT = "Helvetica"
        BOLD_FONT = "Helvetica-Bold"
    _FONTS_READY = True
    return BODY_FONT, BOLD_FONT


# ---------------------------------------------------------------------------
# 마크다운 최소 파서
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^\s*```\s*([A-Za-z0-9_-]*)\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^\s*([-*+]|\d+\.)\s+(.*)$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _split_table_row(line: str) -> list[str]:
    cleaned = line.strip()
    if cleaned.startswith("|"):
        cleaned = cleaned[1:]
    if cleaned.endswith("|"):
        cleaned = cleaned[:-1]
    return [cell.strip() for cell in cleaned.split("|")]


def parse_markdown_blocks(text: str) -> list[dict]:
    """마크다운 문자열을 렌더링 블록 리스트로 변환한다.

    블록 종류: heading / para / bullets / table / chart / code
    파싱에 실패한 ```chart 블록은 그냥 code 블록으로 떨어뜨린다 (크래시 금지).
    """
    import json

    blocks: list[dict] = []
    lines = (text or "").replace("\r\n", "\n").split("\n")
    i = 0
    para_buf: list[str] = []
    bullet_buf: list[str] = []

    def flush_para() -> None:
        if para_buf:
            blocks.append({"kind": "para", "text": " ".join(para_buf).strip()})
            para_buf.clear()

    def flush_bullets() -> None:
        if bullet_buf:
            blocks.append({"kind": "bullets", "items": list(bullet_buf)})
            bullet_buf.clear()

    while i < len(lines):
        line = lines[i]

        fence = _FENCE_RE.match(line)
        if fence:
            lang = (fence.group(1) or "").lower()
            i += 1
            body: list[str] = []
            while i < len(lines) and not _FENCE_RE.match(lines[i]):
                body.append(lines[i])
                i += 1
            i += 1  # 닫는 펜스 소비
            flush_para()
            flush_bullets()
            raw = "\n".join(body)
            if lang == "chart":
                try:
                    spec = ReportChart.model_validate(json.loads(raw))
                    blocks.append({"kind": "chart", "spec": spec})
                except Exception:
                    # 차트 스펙이 깨졌으면 원문을 코드 블록으로 보존한다.
                    blocks.append({"kind": "code", "text": raw})
            else:
                blocks.append({"kind": "code", "text": raw})
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            flush_para()
            flush_bullets()
            blocks.append(
                {"kind": "heading", "level": len(heading.group(1)), "text": heading.group(2).strip()}
            )
            i += 1
            continue

        # 마크다운 표: 헤더행 + 구분행이 연속으로 나와야 표로 인정한다.
        if (
            line.strip().startswith("|")
            and i + 1 < len(lines)
            and _TABLE_SEP_RE.match(lines[i + 1])
        ):
            flush_para()
            flush_bullets()
            header = _split_table_row(line)
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_split_table_row(lines[i]))
                i += 1
            blocks.append({"kind": "table", "header": header, "rows": rows})
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            flush_para()
            bullet_buf.append(bullet.group(2).strip())
            i += 1
            continue

        if not line.strip():
            flush_para()
            flush_bullets()
            i += 1
            continue

        flush_bullets()
        para_buf.append(line.strip())
        i += 1

    flush_para()
    flush_bullets()
    return blocks


_UI_ACTION_HINT_RE = re.compile(r"아래\s*(?:PDF\s*다운로드|이메일\s*발송)\s*버튼으로[^\n]*")


def _strip_trailing_ui_action_hint(content: str) -> str:
    """SYSTEM_PROMPT가 채팅 화면용으로 답변 맨 끝에 붙이도록 지시하는
    "아래 PDF 다운로드 버튼으로 저장할 수 있습니다." / "아래 이메일 발송 버튼으로
    전달할 수 있습니다." 문구를 PDF에서는 제거한다. 챗봇 화면에서는 사용자에게
    다음 행동을 안내하는 유용한 문구지만, PDF 문서 안에서는 가리킬 버튼이 없어
    의미가 없다. 응답 자체(챗 메시지)는 건드리지 않고 PDF 렌더링 직전에만 걸러낸다.

    안내 문구 뒤에 실질적인 내용이 더 남아있으면(=본문 중간에 우연히 같은 표현이
    언급된 경우) 건드리지 않는다 — 진짜 "맨 끝" 안내 문구일 때만 제거한다.
    """
    if not content:
        return content

    match = None
    for match in _UI_ACTION_HINT_RE.finditer(content):
        pass  # 마지막(가장 뒤) 일치만 필요하므로 루프를 끝까지 돌려 덮어쓴다.
    if match is None or content[match.end():].strip():
        return content

    before = content[: match.start()]
    before = re.sub(r"\n[ \t]*-{3,}[ \t]*\n*\Z", "", before)  # 바로 앞 구분선(---)도 함께 제거
    return before.rstrip()


_ESCAPES = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"))
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.S)
_ITALIC_RE = re.compile(r"(?<![\*\w])\*(?!\s)(.+?)(?<!\s)\*(?!\*)", re.S)
_CODE_RE = re.compile(r"`([^`]+)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def markdown_inline_to_rl(text: str) -> str:
    """인라인 마크다운을 reportlab Paragraph 마크업으로 변환 (XML 이스케이프 포함)."""
    out = text or ""
    for src, dst in _ESCAPES:
        out = out.replace(src, dst)
    out = _CODE_RE.sub(lambda m: f'<font face="{MONO_FONT}">{m.group(1)}</font>', out)
    out = _BOLD_RE.sub(lambda m: f"<b>{m.group(1)}</b>", out)
    out = _ITALIC_RE.sub(lambda m: f"<i>{m.group(1)}</i>", out)
    out = _LINK_RE.sub(lambda m: m.group(1), out)
    return out


def _format_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".") if value % 1 else f"{int(value):,}"
    return str(value)


# ---------------------------------------------------------------------------
# 차트 렌더링 (reportlab.graphics — 추가 의존성 없음)
# ---------------------------------------------------------------------------


def _to_number(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        return float(re.sub(r"[^\d.\-]", "", str(value)) or 0)
    except Exception:
        return 0.0


def _chart_drawing(spec: ReportChart, body_font: str):
    """차트 스펙 → reportlab Drawing. 실패하면 None을 반환해 표 폴백을 쓴다."""
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.charts.legends import Legend
    from reportlab.graphics.charts.linecharts import HorizontalLineChart
    from reportlab.graphics.shapes import Drawing

    series = spec.series or []
    if not series or not spec.data:
        return None

    categories = [str(row.get(spec.xKey, "")) for row in spec.data]
    values = [[_to_number(row.get(s.key)) for row in spec.data] for s in series]
    if not any(any(v) for v in values):
        return None

    width, height = 460, 230
    drawing = Drawing(width, height)
    chart = VerticalBarChart() if spec.type == "bar" else HorizontalLineChart()
    chart.x = 45
    chart.y = 55
    chart.width = width - 70
    chart.height = height - 80
    chart.data = values
    chart.categoryAxis.categoryNames = categories
    chart.categoryAxis.labels.fontName = body_font
    chart.categoryAxis.labels.fontSize = 7
    chart.categoryAxis.labels.angle = 30 if len(categories) > 6 else 0
    chart.categoryAxis.labels.dy = -6
    if len(categories) > 6:
        chart.categoryAxis.labels.boxAnchor = "ne"
    chart.valueAxis.labels.fontName = body_font
    chart.valueAxis.labels.fontSize = 7
    chart.valueAxis.labelTextFormat = lambda v: f"{v:,.0f}"
    chart.valueAxis.valueMin = min(0, min(min(v) for v in values))

    for idx in range(len(series)):
        color = SERIES_COLORS[idx % len(SERIES_COLORS)]
        if spec.type == "bar":
            chart.bars[idx].fillColor = color
            chart.bars[idx].strokeColor = None
        else:
            chart.lines[idx].strokeColor = color
            chart.lines[idx].strokeWidth = 1.5

    drawing.add(chart)

    if len(series) > 1:
        legend = Legend()
        legend.x = 45
        legend.y = 20
        legend.alignment = "right"
        legend.fontName = body_font
        legend.fontSize = 8
        legend.columnMaximum = 2
        legend.deltay = 10
        legend.colorNamePairs = [
            (SERIES_COLORS[i % len(SERIES_COLORS)], s.name or s.key)
            for i, s in enumerate(series)
        ]
        drawing.add(legend)

    return drawing


def _chart_as_table_rows(spec: ReportChart) -> tuple[list[str], list[list[str]]]:
    header = [spec.xKey] + [(s.name or s.key) for s in spec.series]
    rows = [
        [str(row.get(spec.xKey, ""))] + [_format_cell(row.get(s.key)) for s in spec.series]
        for row in spec.data
    ]
    return header, rows


# ---------------------------------------------------------------------------
# PDF 조립
# ---------------------------------------------------------------------------


def _styles(body_font: str, bold_font: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "RTitle", parent=base["Title"], fontName=bold_font, fontSize=18, leading=24,
            spaceAfter=4, alignment=TA_LEFT, textColor=colors.HexColor("#0b0b0b"),
        ),
        "subtitle": ParagraphStyle(
            "RSubtitle", parent=base["Normal"], fontName=body_font, fontSize=9.5, leading=14,
            textColor=colors.HexColor("#52514e"), spaceAfter=2,
        ),
        "h1": ParagraphStyle(
            "RH1", parent=base["Normal"], fontName=bold_font, fontSize=14, leading=19,
            spaceBefore=12, spaceAfter=5, textColor=colors.HexColor("#0b0b0b"),
        ),
        "h2": ParagraphStyle(
            "RH2", parent=base["Normal"], fontName=bold_font, fontSize=12, leading=17,
            spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#0b0b0b"),
        ),
        "h3": ParagraphStyle(
            "RH3", parent=base["Normal"], fontName=bold_font, fontSize=10.5, leading=15,
            spaceBefore=8, spaceAfter=3, textColor=colors.HexColor("#26251f"),
        ),
        "body": ParagraphStyle(
            "RBody", parent=base["Normal"], fontName=body_font, fontSize=9.5, leading=15,
            spaceAfter=5, textColor=colors.HexColor("#26251f"),
        ),
        "bullet": ParagraphStyle(
            "RBullet", parent=base["Normal"], fontName=body_font, fontSize=9.5, leading=15,
            leftIndent=12, bulletIndent=3, spaceAfter=2,
            textColor=colors.HexColor("#26251f"),
        ),
        "code": ParagraphStyle(
            "RCode", parent=base["Normal"], fontName=MONO_FONT, fontSize=8, leading=11,
            leftIndent=8, textColor=colors.HexColor("#3d3c37"),
        ),
        "cell": ParagraphStyle(
            "RCell", parent=base["Normal"], fontName=body_font, fontSize=8.5, leading=12,
            textColor=colors.HexColor("#26251f"),
        ),
        "cellhead": ParagraphStyle(
            "RCellHead", parent=base["Normal"], fontName=bold_font, fontSize=8.5, leading=12,
            textColor=colors.HexColor("#0b0b0b"),
        ),
        "caption": ParagraphStyle(
            "RCaption", parent=base["Normal"], fontName=bold_font, fontSize=9.5, leading=14,
            spaceBefore=8, spaceAfter=3, textColor=colors.HexColor("#26251f"),
        ),
    }


def _build_table(header: list[str], rows: list[list[Any]], st: dict, avail_width: float) -> Table:
    header_cells = [Paragraph(markdown_inline_to_rl(str(h)), st["cellhead"]) for h in header]
    body_cells = [
        [Paragraph(markdown_inline_to_rl(_format_cell(c)), st["cell"]) for c in row]
        for row in rows
    ]
    ncols = max(len(header_cells), *(len(r) for r in body_cells)) if body_cells else len(header_cells)
    ncols = max(ncols, 1)
    # 셀 개수가 행마다 다를 수 있으므로 열 수에 맞춰 패딩한다.
    header_cells += [Paragraph("", st["cellhead"])] * (ncols - len(header_cells))
    body_cells = [r + [Paragraph("", st["cell"])] * (ncols - len(r)) for r in body_cells]

    table = Table(
        [header_cells] + body_cells,
        colWidths=[avail_width / ncols] * ncols,
        repeatRows=1,
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f1ea")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.75, colors.HexColor("#c3c2b7")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e1e0d9")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fbfbf8")]),
            ]
        )
    )
    return table


def _footer(canvas_obj, doc) -> None:
    canvas_obj.saveState()
    canvas_obj.setFont(BODY_FONT, 7.5)
    canvas_obj.setFillColor(colors.HexColor("#8a8880"))
    canvas_obj.drawString(20 * mm, 12 * mm, "사내 ERP 매출 분석 챗봇 · 내부용")
    canvas_obj.drawRightString(A4[0] - 20 * mm, 12 * mm, str(canvas_obj.getPageNumber()))
    canvas_obj.restoreState()


def build_pdf(req: PdfReportRequest) -> bytes:
    """리포트 요청 → PDF 바이트. 어떤 입력이 와도 예외 없이 PDF를 만들어야 한다."""
    body_font, bold_font = _ensure_fonts()
    st = _styles(body_font, bold_font)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=20 * mm,
        title=req.title or DEFAULT_TITLE,
        author="ERP 매출 분석 챗봇",
    )
    avail = doc.width

    story: list = [Paragraph(markdown_inline_to_rl(req.title or DEFAULT_TITLE), st["title"])]
    stamp = req.generated_at or datetime.now().strftime("%Y-%m-%d %H:%M")
    story.append(Paragraph("생성 시각: " + markdown_inline_to_rl(str(stamp)), st["subtitle"]))
    story.append(Spacer(1, 10))

    heading_style = {1: "h1", 2: "h2"}
    content = _strip_trailing_ui_action_hint(req.content)

    for block in parse_markdown_blocks(content):
        kind = block["kind"]
        if kind == "heading":
            story.append(
                Paragraph(
                    markdown_inline_to_rl(block["text"]),
                    st[heading_style.get(block["level"], "h3")],
                )
            )
        elif kind == "para":
            story.append(Paragraph(markdown_inline_to_rl(block["text"]), st["body"]))
        elif kind == "bullets":
            for item in block["items"]:
                story.append(
                    Paragraph(markdown_inline_to_rl(item), st["bullet"], bulletText="•")
                )
            story.append(Spacer(1, 4))
        elif kind == "table":
            story.append(Spacer(1, 4))
            story.append(_build_table(block["header"], block["rows"], st, avail))
            story.append(Spacer(1, 8))
        elif kind == "code":
            for line in block["text"].split("\n"):
                story.append(Paragraph(markdown_inline_to_rl(line) or "&nbsp;", st["code"]))
            story.append(Spacer(1, 6))
        elif kind == "chart":
            story.extend(_chart_flowables(block["spec"], st, avail))

    for table in req.tables:
        story.append(Spacer(1, 6))
        if table.title:
            story.append(Paragraph(markdown_inline_to_rl(table.title), st["caption"]))
        story.append(_build_table(table.columns, table.rows, st, avail))
        story.append(Spacer(1, 8))

    for chart in req.charts:
        story.extend(_chart_flowables(chart, st, avail))

    if len(story) <= 3:
        story.append(Paragraph("표시할 조회 결과가 없습니다.", st["body"]))

    try:
        doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    except Exception:
        # 레이아웃 실패(예: 지나치게 넓은 표)에도 최소한의 PDF는 돌려준다.
        buf = io.BytesIO()
        fallback = SimpleDocTemplate(buf, pagesize=A4, title=req.title or DEFAULT_TITLE)
        fallback.build(
            [
                Paragraph(markdown_inline_to_rl(req.title or DEFAULT_TITLE), st["title"]),
                Paragraph(markdown_inline_to_rl(content or ""), st["body"]),
            ]
        )
    return buf.getvalue()


def _chart_flowables(spec: ReportChart, st: dict, avail: float) -> list:
    """차트 1개 → flowable 리스트 (제목 + 그림, 실패 시 데이터 표 폴백)."""
    out: list = [Spacer(1, 6)]
    if spec.title:
        out.append(Paragraph(markdown_inline_to_rl(spec.title), st["caption"]))
    drawing = None
    try:
        drawing = _chart_drawing(spec, BODY_FONT)
    except Exception:
        drawing = None
    if drawing is not None:
        out.append(KeepTogether(drawing))
    else:
        header, rows = _chart_as_table_rows(spec)
        out.append(_build_table(header, rows, st, avail))
    out.append(Spacer(1, 8))
    return out


# ---------------------------------------------------------------------------
# 부가 유틸
# ---------------------------------------------------------------------------

_SAFE_NAME_RE = re.compile(r"[^0-9A-Za-z가-힣._ -]+")


def safe_filename(name: str | None) -> str:
    """경로 구분자/제어문자를 제거한 다운로드 파일명을 만든다."""
    candidate = (name or "").strip().replace("/", "_").replace("\\", "_")
    candidate = _SAFE_NAME_RE.sub("", candidate)
    candidate = re.sub(r"\.{2,}", ".", candidate).strip(" .")
    if not candidate:
        candidate = f"sales_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if not candidate.lower().endswith(".pdf"):
        candidate += ".pdf"
    return candidate[:120]


_CHART_FENCE_RE = re.compile(r"```chart\b", re.I)


def has_reportable_content(reply: str) -> bool:
    """PDF 리포트로 만들 가치가 있는 결과(표 또는 차트)가 응답에 있는지 판정한다.

    프론트가 'PDF 다운로드' 버튼을 노출할지 결정하는 데 쓰는 힌트일 뿐,
    /api/report/pdf는 이 값과 무관하게 어떤 content든 렌더링한다.
    """
    if not reply:
        return False
    if _CHART_FENCE_RE.search(reply):
        return True
    return any(block["kind"] == "table" for block in parse_markdown_blocks(reply))
