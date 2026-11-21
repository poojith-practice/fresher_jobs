"""Subtle A4 interview-prep PDF renderer (reportlab).

Design rules (per user requirements):
- A4 portrait, white background, dark-gray ink, ONE dark-slate accent used
  only for headings and hairline rules. No colored cards, clumsy tables, or logos.
- Deep research summary (Company specialization, interview pattern, priority tech).
- 15-20 technical questions with evidence class badges, relevance rationale,
  bulleted answers in simple English, real-world examples, and code blocks.
- Top 5 priority questions and research gap transparency.
- Clean numbered canvas with 'Page X of Y'.
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
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

INK = colors.HexColor("#242424")        # primary text
MUTED = colors.HexColor("#666666")      # secondary text
ACCENT = colors.HexColor("#2C4152")     # dark slate, headings + rules only
HAIRLINE = colors.HexColor("#DCDCDC")
CODE_BG = colors.HexColor("#F8F8F6")
BOX_BG = colors.HexColor("#FAFAFA")

_FONT = "Helvetica"
_FONT_B = "Helvetica-Bold"
_FONT_I = "Helvetica-Oblique"
_MONO = "Courier"

STYLE_TITLE = ParagraphStyle(
    "title", fontName=_FONT_B, fontSize=18.0, leading=22, textColor=INK,
)
STYLE_SUBTITLE = ParagraphStyle(
    "subtitle", fontName=_FONT, fontSize=11.5, leading=15, textColor=colors.HexColor("#3E3E3E"),
)
STYLE_META = ParagraphStyle(
    "meta", fontName=_FONT, fontSize=8.4, leading=12.0, textColor=MUTED,
)
STYLE_SKILLS = ParagraphStyle(
    "skills", fontName=_FONT, fontSize=9.0, leading=13.0, textColor=INK,
)
STYLE_SUMMARY = ParagraphStyle(
    "summary", fontName=_FONT, fontSize=9.2, leading=13.5, textColor=INK,
)
STYLE_SECTION = ParagraphStyle(
    "section", fontName=_FONT_B, fontSize=11.0, leading=14.5, textColor=ACCENT,
    spaceBefore=5, spaceAfter=3,
)
STYLE_SUBSECTION = ParagraphStyle(
    "subsection", fontName=_FONT_B, fontSize=9.5, leading=13, textColor=INK,
    spaceBefore=3, spaceAfter=2,
)
STYLE_TOPIC = ParagraphStyle(
    "topic", fontName=_FONT_B, fontSize=10.5, leading=14, textColor=ACCENT,
)
STYLE_Q = ParagraphStyle(
    "question", fontName=_FONT_B, fontSize=10.0, leading=13.8, textColor=INK,
)
STYLE_BADGE = ParagraphStyle(
    "badge", fontName=_FONT, fontSize=7.8, leading=10.5, textColor=MUTED,
)
STYLE_RELEVANCE = ParagraphStyle(
    "relevance", fontName=_FONT_I, fontSize=8.5, leading=12.0, textColor=colors.HexColor("#4A4A4A"),
    spaceBefore=1, spaceAfter=2,
)
STYLE_BULLET = ParagraphStyle(
    "bullet", fontName=_FONT, fontSize=9.0, leading=13.0, textColor=INK,
    leftIndent=12, bulletIndent=2, bulletFontName=_FONT, bulletFontSize=9.0,
    spaceBefore=1.5,
)
STYLE_CODE = ParagraphStyle(
    "code", fontName=_MONO, fontSize=7.8, leading=10.2, textColor=colors.HexColor("#333333"),
)
STYLE_CODE_NOTE = ParagraphStyle(
    "codenote", fontName=_FONT, fontSize=8.2, leading=11.5, textColor=MUTED, spaceBefore=2,
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
            self.setFont(_FONT, 7.5)
            self.setFillColor(MUTED)
            self.drawCentredString(PAGE_W / 2.0, 10 * mm, f"Page {self._pageNumber} of {total}")
            super().showPage()
        super().save()


def _slug(text: str) -> str:
    import re

    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(text or "")).strip("_")
    return slug[:60] or "Unknown"


def output_dir_for(base_dir: Path, company: str, role: str) -> Path:
    """<base>/<Company>_<Role>/ directory for one job's documents."""
    return Path(base_dir) / f"{_slug(company)}_{_slug(role)}"


def _esc(text: Any) -> str:
    from interview_prep.curator import escape_for_pdf

    return escape_for_pdf(text)


def _code_block(code: Dict[str, Any]) -> List[Any]:
    flow: List[Any] = []
    if code.get("approach"):
        flow.append(Paragraph(
            f'<b>Approach:</b> {_esc(code["approach"])}',
            ParagraphStyle("approach", parent=STYLE_BULLET, spaceBefore=2),
        ))
    body = str(code.get("code") or "")
    wrapped = "\n".join(
        "\n".join(textwrap.wrap(line, width=90, subsequent_indent="    ")) or ""
        for line in body.splitlines()
    )
    pre = Preformatted(_esc(wrapped), STYLE_CODE)
    table = Table([[pre]], colWidths=[CONTENT_W - 4])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
        ("BOX", (0, 0), (-1, -1), 0.4, HAIRLINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    flow.append(Spacer(1, 3))
    flow.append(table)
    if code.get("complexity"):
        flow.append(Spacer(1, 2))
        flow.append(Paragraph(
            f'<b>Complexity:</b> <font color="#4A4A4A">{_esc(code["complexity"])}</font>',
            STYLE_CODE_NOTE,
        ))
    return flow


def _question_flow(index: int, q: Dict[str, Any]) -> List[Any]:
    flow: List[Any] = []
    topic = str(q.get("topic") or "").strip()
    ev_class = str(q.get("evidence_class") or "D").strip().upper()
    likelihood = str(q.get("likelihood") or "High").strip()
    kind = str(q.get("kind") or "technical").strip()

    class_labels = {
        "A": "Class A (Exact Company/Role)",
        "B": "Class B (Company Historical)",
        "C": "Class C (Stack & Project Overlap)",
        "D": "Class D (JD & Industry Predicted)",
    }
    class_label = class_labels.get(ev_class, f"Class {ev_class}")

    block: List[Any] = []
    # Header: Q# + Topic + Badges
    q_title = f"{index}. {topic}" if topic else f"{index}. {_esc(q['question'])}"
    block.append(Paragraph(_esc(q_title), STYLE_TOPIC))
    block.append(Spacer(1, 1))

    badge_line = f"<b>Evidence:</b> {class_label} &nbsp;·&nbsp; <b>Likelihood:</b> {likelihood} &nbsp;·&nbsp; <b>Type:</b> {kind.capitalize()}"
    block.append(Paragraph(badge_line, STYLE_BADGE))
    block.append(Spacer(1, 2))

    if topic and q.get("question") != topic:
        block.append(Paragraph(f"<b>Question:</b> {_esc(q['question'])}", STYLE_Q))
        block.append(Spacer(1, 2))

    if q.get("relevance"):
        block.append(Paragraph(f"<b>Relevance:</b> {_esc(q['relevance'])}", STYLE_RELEVANCE))
        block.append(Spacer(1, 2))

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
    flow.append(Spacer(1, 8))
    return flow


def _header_flow(job: Dict[str, Any], pack: Dict[str, Any], prepared_at: str) -> List[Any]:
    company = str(job.get("company") or "Target Company")
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
        Paragraph("Technical Interview Prediction & Preparation Guide", STYLE_TITLE),
        Spacer(1, 3),
        Paragraph(f"{_esc(company)} — {_esc(role)}", STYLE_SUBTITLE),
        Spacer(1, 4),
        HRFlowable(width="100%", thickness=0.8, color=ACCENT, spaceBefore=0, spaceAfter=0),
        Spacer(1, 4),
        Paragraph(" &nbsp;·&nbsp; ".join(_esc(m) for m in meta_bits), STYLE_META),
        Spacer(1, 2),
        Paragraph(f"<b>Skills covered:</b> {_esc(skills)}", STYLE_SKILLS),
        Spacer(1, 4),
    ]

    summary = str(pack.get("role_summary") or "").strip()
    if summary:
        flow.append(Paragraph(_esc(summary), STYLE_SUMMARY))
        flow.append(Spacer(1, 5))

    # Executive Research & Evidence Summary Box
    spec = pack.get("company_specialization") or {}
    pat = pack.get("interview_pattern") or {}
    top_techs = pack.get("top_technologies") or []

    if spec or pat or top_techs:
        flow.append(HRFlowable(width="100%", thickness=0.4, color=HAIRLINE))
        flow.append(Spacer(1, 5))
        flow.append(Paragraph("Executive Research & Prediction Summary", STYLE_SECTION))
        flow.append(Spacer(1, 2))

        table_data = []
        if spec.get("primary_business") or spec.get("products_platforms"):
            biz = spec.get("primary_business", "")
            prods = spec.get("products_platforms", "")
            table_data.append([
                Paragraph("<b>Company Domain:</b>", STYLE_SUBSECTION),
                Paragraph(_esc(f"{biz}. Platforms/Products: {prods}" if prods else biz), STYLE_SUMMARY),
            ])
        if spec.get("core_tech_stack"):
            table_data.append([
                Paragraph("<b>Core Tech Stack:</b>", STYLE_SUBSECTION),
                Paragraph(_esc(spec.get("core_tech_stack", "")), STYLE_SUMMARY),
            ])
        if pat.get("rounds_overview") or pat.get("evaluation_focus"):
            r_text = pat.get("rounds_overview", "")
            f_text = pat.get("evaluation_focus", "")
            combined_pat = f"{r_text} (Focus: {f_text})" if f_text else r_text
            table_data.append([
                Paragraph("<b>Interview Pattern:</b>", STYLE_SUBSECTION),
                Paragraph(_esc(combined_pat), STYLE_SUMMARY),
            ])
        if top_techs:
            tech_line = " &nbsp;·&nbsp; ".join(_esc(t) for t in top_techs[:6])
            table_data.append([
                Paragraph("<b>Priority Focus:</b>", STYLE_SUBSECTION),
                Paragraph(tech_line, STYLE_SUMMARY),
            ])

        if table_data:
            summary_table = Table(table_data, colWidths=[38 * mm, CONTENT_W - (38 * mm) - 4])
            summary_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), BOX_BG),
                ("BOX", (0, 0), (-1, -1), 0.4, HAIRLINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            flow.append(summary_table)
            flow.append(Spacer(1, 6))

    flow.append(HRFlowable(width="100%", thickness=0.4, color=HAIRLINE))
    flow.append(Spacer(1, 6))
    flow.append(Paragraph("Most Probable Technical Interview Questions", STYLE_SECTION))
    flow.append(Spacer(1, 4))
    return flow


def _strategic_prep_flow(pack: Dict[str, Any]) -> List[Any]:
    flow: List[Any] = []
    top_5 = pack.get("top_5_questions_to_prepare_first") or []
    more_coding = pack.get("more_coding_questions") or []

    if top_5 or more_coding:
        flow.append(Spacer(1, 4))
        flow.append(HRFlowable(width="100%", thickness=0.6, color=ACCENT))
        flow.append(Spacer(1, 6))
        flow.append(Paragraph("Strategic Preparation", STYLE_SECTION))
        flow.append(Spacer(1, 3))

    if top_5:
        top5_block: List[Any] = [
            Paragraph("Top 5 Questions to Prepare First (Highest Preparation Yield):", STYLE_SUBSECTION),
            Spacer(1, 2),
        ]
        for idx, item in enumerate(top_5, 1):
            top5_block.append(Paragraph(_esc(item), STYLE_BULLET, bulletText=f"{idx}."))
        flow.append(KeepTogether(top5_block))
        flow.append(Spacer(1, 6))

    if more_coding:
        coding_block: List[Any] = [
            Paragraph("Additional Coding Practice Questions (Reported / Relevant):", STYLE_SUBSECTION),
            Paragraph(
                "These problems represent algorithmic and coding patterns common in technical assessments for this role family. Practice these independently before interview rounds.",
                STYLE_CODE_NOTE,
            ),
            Spacer(1, 3),
        ]
        for idx, problem in enumerate(more_coding, 1):
            coding_block.append(Paragraph(_esc(problem), STYLE_BULLET, bulletText=f"{idx}."))
        flow.append(KeepTogether(coding_block))
        flow.append(Spacer(1, 6))

    return flow


def render_interview_pdf(
    job: Dict[str, Any],
    pack: Dict[str, Any],
    pdf_path: Path,
    prepared_at: str,
) -> Path:
    """Render the pack as a subtle, research-backed A4 PDF. Returns the written path."""
    pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Interview Prep - {job.get('company', '')} {job.get('tech_category') or job.get('title', '')}",
        author="Fresher Job Intelligence Pipeline",
    )

    story: List[Any] = []
    story.extend(_header_flow(job, pack, prepared_at))

    questions: List[Dict[str, Any]] = pack.get("questions") or []
    for i, q in enumerate(questions, 1):
        story.extend(_question_flow(i, q))

    story.extend(_strategic_prep_flow(pack))

    doc.build(story, canvasmaker=_NumberedCanvas)
    logger.info("Rendered %s (%d questions)", pdf_path, len(questions))
    return pdf_path
