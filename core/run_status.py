"""Machine-readable run outcomes for the scraping pipeline.

Why this exists
---------------
Before this module the pipeline could finish a run with exit code 0 after every
board had been blocked, and the only trace was an empty CSV or an empty Google
Sheet. An empty sheet is indistinguishable from "there were genuinely no new
fresher jobs today". That violates two rules of this project:

* never silently suppress a scraping failure;
* never report an unsuccessful scrape as a successful zero-job scrape.

Every adapter result is therefore classified into one of the states below, and
the run as a whole gets exactly one outcome that says which of those situations
actually happened.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

# ---------------------------------------------------------------------------
# Per-source states
# ---------------------------------------------------------------------------
SOURCE_OK = "ok"                            # request succeeded and returned rows
SOURCE_EMPTY = "empty"                      # request succeeded, board had nothing
SOURCE_BLOCKED = "blocked"                  # 401/403/406/999/captcha
SOURCE_RATE_LIMITED = "rate_limited"        # 429
SOURCE_AUTH_FAILURE = "auth_failure"        # missing/invalid API key or session
SOURCE_PARSER_FAILURE = "parser_failure"    # 200 but no recognisable job payload
SOURCE_NETWORK_FAILURE = "network_failure"  # DNS/timeout/connection reset
SOURCE_ERROR = "error"                      # anything else, with the message kept
SOURCE_SKIPPED = "skipped"                  # deliberately not attempted

FAILURE_STATES = frozenset({
    SOURCE_BLOCKED,
    SOURCE_RATE_LIMITED,
    SOURCE_AUTH_FAILURE,
    SOURCE_PARSER_FAILURE,
    SOURCE_NETWORK_FAILURE,
    SOURCE_ERROR,
})

# ---------------------------------------------------------------------------
# Whole-run outcomes
# ---------------------------------------------------------------------------
OUTCOME_SUCCESS = "SUCCESS_WITH_JOBS"
OUTCOME_NO_JOBS = "NO_JOBS_FOUND"
OUTCOME_ALL_REJECTED = "ALL_JOBS_REJECTED_BY_FILTERS"
OUTCOME_PARTIAL = "PARTIAL_SOURCE_FAILURE"
OUTCOME_ALL_FAILED = "ALL_SOURCES_FAILED"
OUTCOME_PARSER_FAILED = "ALL_SOURCES_PARSER_FAILURE"
OUTCOME_PIPELINE_FAILED = "PIPELINE_FAILED"

# Exit codes. Only genuine infrastructure failures are non-zero, so a scheduled
# workflow turns red exactly when a human needs to look at it.
EXIT_CODES = {
    OUTCOME_SUCCESS: 0,
    OUTCOME_NO_JOBS: 0,
    OUTCOME_ALL_REJECTED: 0,
    OUTCOME_PARTIAL: 0,
    OUTCOME_ALL_FAILED: 2,
    OUTCOME_PARSER_FAILED: 2,
    OUTCOME_PIPELINE_FAILED: 3,
}


def classify_source(error: Optional[str], row_count: int, attempted: bool = True) -> str:
    """Map one adapter result to a source state.

    ``error`` is the message the adapter or JobSpy reported, if any. It is
    matched case-insensitively because adapters word things differently.
    """
    if not attempted:
        return SOURCE_SKIPPED
    if not error:
        return SOURCE_OK if row_count > 0 else SOURCE_EMPTY

    text = str(error).lower()

    if any(x in text for x in ("429", "rate limit", "too many requests", "free-models-per-day")):
        return SOURCE_RATE_LIMITED
    if any(x in text for x in ("api key", "unauthenticated", "unauthorized", "invalid_api_key", "401")):
        return SOURCE_AUTH_FAILURE
    if any(x in text for x in ("406", "recaptcha", "captcha", "human verification", "999")):
        return SOURCE_BLOCKED
    if any(x in text for x in ("403", "forbidden", "blocked", "access denied")):
        return SOURCE_BLOCKED
    if any(x in text for x in ("no jobs", "unexpected page", "could not parse", "parse", "no title", "no company", "no location")):
        return SOURCE_PARSER_FAILURE
    if any(x in text for x in ("timeout", "timed out", "connection", "dns", "resolve", "ssl", "network")):
        return SOURCE_NETWORK_FAILURE
    return SOURCE_ERROR


@dataclass
class SourceRecord:
    """What one source did during one run."""

    source: str
    attempts: int = 0
    rows: int = 0
    states: Dict[str, int] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def add_attempt(self, state: str, rows: int = 0, error: Optional[str] = None) -> None:
        self.attempts += 1
        self.rows += max(0, rows)
        self.states[state] = self.states.get(state, 0) + 1
        if error:
            message = str(error)
            if message not in self.errors:
                self.errors.append(message)

    @property
    def dominant_state(self) -> str:
        """The state that best describes the source.

        Any rows win: a board that returned jobs worked, even if a later query
        was throttled. Otherwise the most frequent failure state is reported.
        """
        if self.rows > 0:
            return SOURCE_OK
        if not self.states:
            return SOURCE_SKIPPED
        for preferred in (
            SOURCE_BLOCKED,
            SOURCE_RATE_LIMITED,
            SOURCE_AUTH_FAILURE,
            SOURCE_PARSER_FAILURE,
            SOURCE_NETWORK_FAILURE,
            SOURCE_ERROR,
            SOURCE_EMPTY,
        ):
            if preferred in self.states:
                return preferred
        return SOURCE_EMPTY

    @property
    def failed(self) -> bool:
        return self.rows == 0 and self.dominant_state in FAILURE_STATES

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "attempts": self.attempts,
            "rows": self.rows,
            "state": self.dominant_state,
            "states": dict(self.states),
            "errors": self.errors[:5],
        }


@dataclass
class RunReport:
    """Evidence for one pipeline execution."""

    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0.0
    queries: int = 0
    raw_total: int = 0
    unique_total: int = 0
    approved: int = 0
    rejected: int = 0
    review: int = 0
    sources: Dict[str, SourceRecord] = field(default_factory=dict)
    outcome: str = OUTCOME_NO_JOBS
    notes: List[str] = field(default_factory=list)

    def source(self, name: str) -> SourceRecord:
        record = self.sources.get(name)
        if record is None:
            record = SourceRecord(source=name)
            self.sources[name] = record
        return record

    # -- outcome -----------------------------------------------------------
    def classify(self) -> str:
        attempted = [s for s in self.sources.values() if s.attempts > 0]
        if not attempted:
            return OUTCOME_PIPELINE_FAILED

        failed = [s for s in attempted if s.failed]
        healthy = [s for s in attempted if not s.failed]

        if not healthy and failed:
            if all(s.dominant_state == SOURCE_PARSER_FAILURE for s in failed):
                return OUTCOME_PARSER_FAILED
            return OUTCOME_ALL_FAILED
        if failed and healthy:
            return OUTCOME_PARTIAL
        if self.approved > 0:
            return OUTCOME_SUCCESS
        if self.raw_total == 0:
            return OUTCOME_NO_JOBS
        return OUTCOME_ALL_REJECTED

    @property
    def exit_code(self) -> int:
        return EXIT_CODES.get(self.outcome, 1)

    @property
    def has_infrastructure_failure(self) -> bool:
        return self.outcome in {OUTCOME_ALL_FAILED, OUTCOME_PARSER_FAILED, OUTCOME_PIPELINE_FAILED}

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["sources"] = {name: rec.to_dict() for name, rec in self.sources.items()}
        data["outcome"] = self.outcome
        data["exit_code"] = self.exit_code
        data["healthy_sources"] = sorted(n for n, r in self.sources.items() if r.attempts and not r.failed)
        data["failed_sources"] = sorted(n for n, r in self.sources.items() if r.failed)
        return data

    # -- rendering ---------------------------------------------------------
    def headline(self) -> str:
        return {
            OUTCOME_SUCCESS: "Jobs collected and approved",
            OUTCOME_NO_JOBS: "No jobs found (sources responded normally)",
            OUTCOME_ALL_REJECTED: "Jobs were found but none passed the fresher gates",
            OUTCOME_PARTIAL: "Some sources failed; jobs collected from the rest",
            OUTCOME_ALL_FAILED: "Every source failed - this is NOT a zero-job result",
            OUTCOME_PARSER_FAILED: "Every source returned unusable output - parser failure",
            OUTCOME_PIPELINE_FAILED: "Pipeline failed before any source ran",
        }.get(self.outcome, self.outcome)

    def render_markdown(self) -> str:
        lines = [
            "# Scrape run report",
            "",
            f"- **Outcome:** `{self.outcome}` — {self.headline()}",
            f"- **Started:** {self.started_at}",
            f"- **Duration:** {self.duration_seconds:.1f}s",
            f"- **Queries:** {self.queries}",
            f"- **Raw listings:** {self.raw_total}",
            f"- **Unique after dedup:** {self.unique_total}",
            f"- **Approved / rejected / review:** {self.approved} / {self.rejected} / {self.review}",
            "",
            "## Sources",
            "",
            "| Source | Attempts | Rows | State | Detail |",
            "|---|---|---|---|---|",
        ]
        for name in sorted(self.sources):
            rec = self.sources[name]
            detail = "; ".join(rec.errors[:2]) if rec.errors else "-"
            detail = detail.replace("|", "/")[:180]
            lines.append(f"| `{name}` | {rec.attempts} | {rec.rows} | `{rec.dominant_state}` | {detail} |")

        if self.notes:
            lines += ["", "## Notes", ""] + [f"- {n}" for n in self.notes]
        return "\n".join(lines) + "\n"

    def write(self, directory: str | Path, stem: str = "run_report") -> Dict[str, str]:
        """Write JSON plus Markdown evidence into ``directory``."""
        out_dir = Path(directory)
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / f"{stem}.json"
        md_path = out_dir / f"{stem}.md"
        payload = self.to_dict()
        payload["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        md_path.write_text(self.render_markdown(), encoding="utf-8")
        return {"json": str(json_path), "markdown": str(md_path)}


def build_report_from_stats(
    stats: Dict[str, Any],
    started_at: Optional[str] = None,
) -> RunReport:
    """Create a :class:`RunReport` from the dict ``scrape_fresher_jobs`` returns."""
    report = RunReport(
        started_at=started_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        duration_seconds=float(stats.get("duration_seconds") or 0.0),
        queries=int(stats.get("total_queries_executed") or 0),
        raw_total=int(stats.get("total_raw_scraped") or 0),
        unique_total=int(stats.get("total_unique_jobs") or 0),
        approved=int(stats.get("valid_fresher_jobs") or 0),
        rejected=int(stats.get("rejected_jobs_count") or 0),
        review=int(stats.get("review_jobs_count") or 0),
    )

    raw_by_site = stats.get("raw_by_site") or {}
    diagnostics = stats.get("source_diagnostics") or {}
    attempts = stats.get("site_queries_attempted") or {}

    for source, diag in diagnostics.items():
        rec = report.source(source)
        rec.attempts = int(diag.get("attempts") or 0)
        rec.rows = int(raw_by_site.get(source, 0) or 0)
        rec.states = dict(diag.get("states") or {})
        rec.errors = list(diag.get("errors") or [])
        if not rec.states:
            error = "; ".join(stats.get("site_errors", {}).get(source, []))
            rec.states = {classify_source(error or None, rec.rows): 1}

    # Sources that were configured and executed:
    for source, source_attempts in attempts.items():
        if source not in report.sources:
            rec = report.source(source)
            rec.attempts = int(source_attempts or 0)
            rec.rows = int(raw_by_site.get(source, 0) or 0)
            err_list = stats.get("site_errors", {}).get(source, [])
            error = "; ".join(err_list) if err_list else None
            rec.states = {classify_source(error, rec.rows): 1}
        elif report.sources[source].attempts == 0 and source_attempts:
            report.sources[source].attempts = int(source_attempts)

    for source, errors in (stats.get("site_errors") or {}).items():
        if source in report.sources:
            for message in errors:
                if message not in report.sources[source].errors:
                    report.sources[source].errors.append(str(message))

    report.outcome = report.classify()
    return report
