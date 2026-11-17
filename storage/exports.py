"""
Tabular Export Engine (CSV & Excel)
===================================
Produces comprehensive, multi-tab Excel and clean CSV files for approved,
rejected, and manual-review fresher opportunities with full provenance and skills breakdown.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

from core.models import (
    Opportunity,
    FinalApprovalStatus,
)

logger = logging.getLogger("storage.exports")

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

CSV_HEADERS = [
    "Opportunity ID",
    "Job Title",
    "Company Name",
    "Opportunity Type",
    "Role Family",
    "Location",
    "Date Posted",
    "Experience Required",
    "Eligible Batches",
    "Deadline",
    "Deadline Status",
    "Apply URL",
    "Source Name",
    "Company Verification",
    "Required Skills",
    "Preferred Skills",
    "All Extracted Skills",
    "Skills Status",
    "LLM Reasoning",
    "Deterministic Status",
    "Final Status",
    "Rejection / Review Reasons",
]


def _format_opportunity_row(opp: Opportunity) -> List[Any]:
    """Flattens an Opportunity model into a row for CSV/Excel."""
    batches_str = ", ".join(str(b) for b in opp.eligible_graduation_batches) if opp.eligible_graduation_batches else "Not specified"
    loc_str = ", ".join(opp.location) if opp.location else "India"
    all_skills_str = ", ".join(opp.skills) if opp.skills else "None Published"
    req_skills_str = ", ".join(s.name for s in opp.required_skills) if opp.required_skills else "None Published"
    pref_skills_str = ", ".join(s.name for s in opp.preferred_skills) if opp.preferred_skills else "None"
    reasons_str = "; ".join(opp.rejection_reasons or opp.manual_review_reasons) if (opp.rejection_reasons or opp.manual_review_reasons) else "None"

    return [
        opp.opportunity_id,
        opp.title,
        opp.company,
        opp.opportunity_type.value,
        opp.role_family,
        loc_str,
        opp.date_posted or "Not published",
        opp.experience_status or "0-1 Years",
        batches_str,
        opp.deadline or "Not published",
        opp.deadline_status.value,
        opp.apply_url or opp.source_detail_url or "",
        opp.source_name,
        opp.company_verification_status.value,
        req_skills_str,
        pref_skills_str,
        all_skills_str,
        opp.skills_extraction_status,
        opp.llm_reasoning or "Deterministic evaluation",
        opp.deterministic_status.value,
        opp.final_status.value,
        reasons_str,
    ]


def export_to_csv(opportunities: List[Opportunity], output_filename: str = "verified_fresher_jobs.csv") -> Path:
    """Exports opportunities to CSV.
    
    CRITICAL PURITY RULE:
    verified_fresher_jobs.csv must strictly contain ONLY opportunities where
    final_status == FinalApprovalStatus.APPROVED.
    Rejected and manual-review opportunities are partitioned into dedicated CSVs.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target_path = OUTPUT_DIR / output_filename

    if output_filename == "verified_fresher_jobs.csv":
        approved_opps = [o for o in opportunities if o.final_status == FinalApprovalStatus.APPROVED]
        rejected_opps = [o for o in opportunities if o.final_status == FinalApprovalStatus.REJECTED]
        manual_opps = [o for o in opportunities if o.final_status == FinalApprovalStatus.MANUAL_REVIEW]

        # Invariant check before exporting approved dataset
        from verification.final_approval import assert_approval_invariants
        for rec in approved_opps:
            assert_approval_invariants(rec)

        # 1. Main verified jobs file (Strictly APPROVED only)
        with open(target_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)
            for opp in approved_opps:
                writer.writerow(_format_opportunity_row(opp))
        logger.info("[exports] Exported %d APPROVED records to %s", len(approved_opps), target_path)

        # 2. Partitioned rejected file
        rejected_path = OUTPUT_DIR / "rejected_fresher_jobs.csv"
        with open(rejected_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)
            for opp in rejected_opps:
                writer.writerow(_format_opportunity_row(opp))
        logger.info("[exports] Exported %d REJECTED records to %s", len(rejected_opps), rejected_path)

        # 3. Partitioned manual review file
        manual_path = OUTPUT_DIR / "manual_review_fresher_jobs.csv"
        with open(manual_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)
            for opp in manual_opps:
                writer.writerow(_format_opportunity_row(opp))
        logger.info("[exports] Exported %d MANUAL_REVIEW records to %s", len(manual_opps), manual_path)

        return target_path

    # Custom filename
    with open(target_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADERS)
        for opp in opportunities:
            writer.writerow(_format_opportunity_row(opp))

    logger.info("[exports] Successfully exported %d records to %s", len(opportunities), target_path)
    return target_path


def export_to_excel(
    all_opportunities: List[Opportunity],
    output_filename: str = "verified_fresher_jobs.xlsx",
) -> Path:
    """Exports opportunities into a styled multi-tab Excel workbook."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target_path = OUTPUT_DIR / output_filename

    wb = openpyxl.Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    approved = [o for o in all_opportunities if o.final_status == FinalApprovalStatus.APPROVED]
    manual_review = [o for o in all_opportunities if o.final_status == FinalApprovalStatus.MANUAL_REVIEW]
    rejected = [o for o in all_opportunities if o.final_status == FinalApprovalStatus.REJECTED]

    # Invariant assertion check before saving approved tab
    from verification.final_approval import assert_approval_invariants
    for rec in approved:
        assert_approval_invariants(rec)

    # Tab 1: Approved
    _populate_sheet(wb, "Approved Opportunities", approved, header_color="1B5E20")  # Dark green
    # Tab 2: Manual Review
    _populate_sheet(wb, "Manual Review", manual_review, header_color="E65100")     # Dark orange
    # Tab 3: Rejected
    _populate_sheet(wb, "Rejected Opportunities", rejected, header_color="B71C1C") # Dark red
    # Tab 4: Source Metrics
    _populate_metrics_sheet(wb, all_opportunities)

    wb.save(target_path)
    logger.info("[exports] Successfully exported multi-tab workbook to %s", target_path)
    return target_path


def _populate_sheet(wb: openpyxl.Workbook, sheet_title: str, opportunities: List[Opportunity], header_color: str):
    ws = wb.create_sheet(title=sheet_title)
    ws.views.sheetView[0].showGridLines = True

    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color=header_color, end_color=header_color, fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    ws.append(CSV_HEADERS)
    ws.row_dimensions[1].height = 28

    for col_idx in range(1, len(CSV_HEADERS) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment

    for opp in opportunities:
        row_data = _format_opportunity_row(opp)
        ws.append(row_data)

    # Auto-adjust column widths
    for col in ws.columns:
        max_len = 0
        col_letter = col[0].column_letter
        for cell in col[:50]:
            val_str = str(cell.value or "")
            if len(val_str) > max_len:
                max_len = len(val_str)
        ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 40)


def _populate_metrics_sheet(wb: openpyxl.Workbook, opportunities: List[Opportunity]):
    ws = wb.create_sheet(title="Source & Quality Metrics")
    ws.views.sheetView[0].showGridLines = True

    title_font = Font(name="Calibri", size=14, bold=True, color="0D47A1")
    section_font = Font(name="Calibri", size=12, bold=True)
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="0D47A1", end_color="0D47A1", fill_type="solid")

    ws.append(["Fresher Job Intelligence Scraper — Quality & Coverage Metrics"])
    ws.cell(row=1, column=1).font = title_font
    ws.append([])

    # 1. Overall Summary
    total = len(opportunities)
    approved = sum(1 for o in opportunities if o.final_status == FinalApprovalStatus.APPROVED)
    rejected = sum(1 for o in opportunities if o.final_status == FinalApprovalStatus.REJECTED)
    manual = sum(1 for o in opportunities if o.final_status == FinalApprovalStatus.MANUAL_REVIEW)

    ws.append(["Metric", "Count", "Percentage"])
    ws.row_dimensions[3].height = 24
    for c in range(1, 4):
        cell = ws.cell(row=3, column=c)
        cell.font = header_font
        cell.fill = header_fill

    ws.append(["Total Opportunities Discovered", total, "100.0%"])
    ws.append(["Approved Opportunities", approved, f"{(approved/total*100):.1f}%" if total else "0%"])
    ws.append(["Rejected Opportunities", rejected, f"{(rejected/total*100):.1f}%" if total else "0%"])
    ws.append(["Manual Review Required", manual, f"{(manual/total*100):.1f}%" if total else "0%"])
    ws.append([])

    # 2. Source Breakdown
    ws.append(["Source Name", "Discovered", "Approved", "Approval Rate"])
    row_idx = ws.max_row
    for c in range(1, 5):
        cell = ws.cell(row=row_idx, column=c)
        cell.font = header_font
        cell.fill = header_fill

    sources = sorted(list(set(o.source_name for o in opportunities)))
    for s in sources:
        s_total = sum(1 for o in opportunities if o.source_name == s)
        s_app = sum(1 for o in opportunities if o.source_name == s and o.final_status == FinalApprovalStatus.APPROVED)
        rate = f"{(s_app/s_total*100):.1f}%" if s_total else "0%"
        ws.append([s, s_total, s_app, rate])

    for col in ws.columns:
        col_letter = col[0].column_letter
        ws.column_dimensions[col_letter].width = 25
