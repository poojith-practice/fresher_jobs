"""Subtle A4 interview-prep PDF renderer (reportlab).

Design rules (per user requirements):
- A4 portrait, white background, dark-gray ink, ONE dark-slate accent used
  only for headings and hairline rules. No colored cards, tables, or logos.
- Short bullet answers in neutral voice; an "Example:" bullet only where the
  pack provides one; coding answers show a short approach plus compact code.
- Numbered questions, generous spacing, nothing congested.
"""
from __future__ import annotations

import logging
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger("interview_prep.pdf")

PAGE_W, PAGE_H = A4
MARGIN = 19 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

INK = colors.HexColor("#242424")        # primary text
MUTED = colors.HexColor("#6B6B6B")      # secondary text
ACCENT = colors.HexColor("#2C4152")     # dark slate, headings + rules only
HAIRLINE = colors.HexColor("#DCDCDC")
CODE_BG = colors.HexColor("#F6F6F4")

_FONT = "Helvetica"
_FONT_B = "Helvetica-Bold"
_MONO = "Courier"

STYLE_TITLE = ParagraphStyle(
    "title", fontName=_FONT_B, fontSize=18.5, leading=23, textColor=INK,
)
STYLE_SUBTITLE = ParagraphStyle(
    "subtitle", fontName=_FONT, fontSize=11.5, leading=15, textColor=colors.HexColor("#3E3E3E"),
)
STYLE_META = ParagraphStyle(
    "meta", fontName=_FONT, fontSize=8.6, leading=12.5, textColor=MUTED,
)
STYLE_SKILLS = ParagraphStyle(
    "skills", fontName=_FONT, fontSize=9.1, leading=13.5, textColor=INK,
)
STYLE_SUMMARY = ParagraphStyle(
    "summary", fontName=_FONT, fontSize=9.6, leading=14, textColor=INK,
)
STYLE_SECTION = ParagraphStyle(
    "section", fontName=_FONT_B, fontSize=11.5, leading=15, textColor=ACCENT,
    spaceBefore=4,
)
STYLE_Q = ParagraphStyle(
    "question", fontName=_FONT_B, fontSize=10.4, leading=14.2, textColor=INK,
)
STYLE_BULLET = ParagraphStyle(
    "bullet", fontName=_FONT, fontSize=9.4, leading=13.4, textColor=INK,
    leftIndent=13, bulletIndent=3, bulletFontName=_FONT, bulletFontSize=9.4,
    spaceBefore=1.5,
)
STYLE_CODE = ParagraphStyle(
    "code", fontName=_MONO, fontSize=8.0, leading=10.6, textColor=colors.HexColor("#3A3A3A"),
)
STYLE_CODE_NOTE = ParagraphStyle(
    "codenote", fontName=_FONT, fontSize=8.4, leading=12, textColor=MUTED, spaceBefore=2,
)


class _NumberedCanvas(pdfcanvas.Canvas):
    """Two-pass canvas that stamps 'Page X of Y' at the bottom center."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._saved_states: list[dict] = []

    def showPage(self) -> None:  # noqa: D102 - reportlab API
        self._saved_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:  # noqa: D102 - reportlab API
        total = len(self._saved_states)
        for state in self._saved_states:
            self.__dict__.update(state)
            self.setFont(_FONT, 7.6)
            self.setFillColor(MUTED)
            self.drawCentredString(PAGE_W / 2.0, 11 * mm, f"Page {self._pageNumber} of {total}")
            super().showPage()
        super().save()


def _slug(text: str) -> str:
    import re

    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(text or "")).strip("_")
    return slug[:60] or "Unknown"


def output_dir_for(base_dir: Path, company: str, role: str) -> Path:
    """<base>/<Company>_<Role>/ directory for one job's documents."""
    return Path(base_dir) / f"{_slug(company)}_{_slug(role)}"


def _question_tag(q: Dict[str, Any]) -> str:
    tags = []
    if q.get("kind") == "coding":
        tags.append("coding")
    if q.get("origin") == "company":
        tags.append("company-specific")
    if not tags:
        return ""
    return f' <font size="7.4" color="#6B6B6B">·&nbsp;{" · ".join(tags)}</font>'


def _code_block(code: Dict[str, Any]) -> List[Any]:
    flow: List[Any] = []
    if code.get("approach"):
        flow.append(Paragraph(
            f'<b>Approach:</b> {code["approach"]}',
            ParagraphStyle("approach", parent=STYLE_BULLET),
        ))
    body = str(code.get("code") or "")
    wrapped = "\n".join(
        "\n".join(textwrap.wrap(line, width=88, subsequent_indent="    ")) or ""
        for line in body.splitlines()
    )
    pre = Preformatted(wrapped, STYLE_CODE)
    table = Table([[pre]], colWidths=[CONTENT_W - 4])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
        ("BOX", (0, 0), (-1, -1), 0.4, HAIRLINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    flow.append(Spacer(1, 3))
    flow.append(table)
    return flow


def _question_flow(index: int, q: Dict[str, Any]) -> List[Any]:
    flow: List[Any] = []
    head = f"{index}. {_esc(q['question'])}{_question_tag(q)}"
    block: List[Any] = [Paragraph(head, STYLE_Q), Spacer(1, 2.5)]
    for bullet in q.get("answer_bullets") or []:
        block.append(Paragraph(_esc(bullet), STYLE_BULLET, bulletText="–"))
    if q.get("example"):
        block.append(Paragraph(
            f'<b><i>Example:</i></b> {_esc(q["example"])}',
            ParagraphStyle("example", parent=STYLE_BULLET),
            bulletText="–",
        ))
    if q.get("code"):
        block.extend(_code_block(q["code"]))
    flow.append(KeepTogether(block))
    flow.append(Spacer(1, 9))
    return flow


def _esc(text: Any) -> str:
    from interview_prep.curator import escape_for_pdf

    return escape_for_pdf(text)


def _header_flow(job: Dict[str, Any], pack: Dict[str, Any], prepared_at: str) -> List[Any]:
    company = str(job.get("company") or "Unknown company")
    role = str(job.get("tech_category") or job.get("title") or "Fresher role")
    skills = job.get("skills_requirements") or job.get("required_skills") or ""
    if isinstance(skills, (list, tuple)):
        skills = ", ".join(str(s) for s in skills)

    meta_bits = [
        f"Location: {job.get('location') or 'India'}",
        f"Source: {str(job.get('site') or '').capitalize() or 'Job board'}",
        f"Posted: {job.get('date_posted') or 'n/a'}",
        f"Prepared: {prepared_at}",
    ]
    flow: List[Any] = [
        Paragraph("Interview Preparation Guide", STYLE_TITLE),
        Spacer(1, 3),
        Paragraph(f"{_esc(company)} — {_esc(role)}", STYLE_SUBTITLE),
        Spacer(1, 5),
        HRFlowable(width="100%", thickness=0.8, color=ACCENT, spaceBefore=0, spaceAfter=0),
        Spacer(1, 5),
        Paragraph(" &nbsp;·&nbsp; ".join(_esc(m) for m in meta_bits), STYLE_META),
        Spacer(1, 3),
        Paragraph(f"<b>Skills covered:</b> {_esc(skills)}", STYLE_SKILLS),
        Spacer(1, 4),
    ]
    summary = str(pack.get("role_summary") or "").strip()
    if summary:
        flow.append(Paragraph(_esc(summary), STYLE_SUMMARY))
    flow.append(Spacer(1, 8))
    flow.append(HRFlowable(width="100%", thickness=0.4, color=HAIRLINE))
    flow.append(Spacer(1, 10))
    return flow


def _more_coding_flow(more: List[str]) -> List[Any]:
    flow: List[Any] = [
        HRFlowable(width="100%", thickness=0.4, color=HAIRLINE),
        Spacer(1, 8),
        Paragraph("Coding questions asked previously", STYLE_SECTION),
        Spacer(1, 3),
        Paragraph(
            "These coding questions were reported in past interview experiences for this "
            "kind of role. Practice them on your own before the interview.",
            STYLE_CODE_NOTE,
        ),
        Spacer(1, 4),
    ]
    block: List[Any] = []
    for i, question in enumerate(more, 1):
        block.append(Paragraph(_esc(question), STYLE_BULLET, bulletText=f"{i}."))
    flow.append(KeepTogether(block))
    return flow


def render_interview_pdf(
    job: Dict[str, Any],
    pack: Dict[str, Any],
    pdf_path: Path,
    prepared_at: str,
) -> Path:
    """Render the pack as a subtle A4 PDF. Returns the written path."""
    pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=18 * mm,
        bottomMargin=17 * mm,
        title=f"Interview Prep - {job.get('company', '')} {job.get('tech_category') or job.get('title', '')}",
        author="Fresher Job Intelligence Pipeline",
    )

    story: List[Any] = []
    story.extend(_header_flow(job, pack, prepared_at))

    questions: List[Dict[str, Any]] = pack.get("questions") or []
    for i, q in enumerate(questions, 1):
        story.extend(_question_flow(i, q))

    more = pack.get("more_coding_questions") or []
    if more:
        story.extend(_more_coding_flow(more))

    doc.build(story, canvasmaker=_NumberedCanvas)
    logger.info("Rendered %s (%d questions)", pdf_path, len(questions))
    return pdf_path
