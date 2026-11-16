# Fresher Job Scraper & Intelligence Platform — Complete Project Blueprint

> **System Version**: 2.0 (Deep Research, Multi-Source Intelligence & Production Gating)  
> **Target Audience**: Placement Officers, Software Engineers, System Architects, and Academic Coordinators  
> **Repository**: `poojithinavolu/fresher_jobs`  
> **Last Updated**: November 2026  

---

## 1. Executive Project Overview

The **Fresher Job Scraper & Intelligence Platform** is an enterprise-grade automated ecosystem designed to discover, strictly verify, curate, and distribute entry-level (fresher) employment opportunities across India. It solves the endemic challenge of "experience inflation"—where job listings labeled as *entry-level* secretly require 2–5 years of commercial experience—by coupling deterministic multi-layered rule filtering with multi-provider LLM verification.

Beyond job aggregation, the platform features a complete **Technical Interview Prediction Engine (v2.0)** that executes autonomous OSINT and academic research on target employers, generating publication-quality, 20-question company-specific interview preparation dossiers in subtle, elegant A4 PDF format for students.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                   END-TO-END PIPELINE                                   │
└────────────────────────────────────────────────────────────────────────────────────────┘

 [ JobSpy (Naukri, Indeed, LinkedIn) ]       [ Foundit Scraper (primp / curl_cffi) ]
                   │                                            │
                   └─────────────────────┬──────────────────────┘
                                         ▼
                     ┌───────────────────────────────────────┐
                     │     1. Deterministic Filter Engine    │  ◄── Rule-based: Exp <= 1 yr,
                     │          (filter_engine.py)           │      Freshness <= 20/48 hrs,
                     └───────────────────┬───────────────────┘      Location & Title Blacklist
                                         ▼
                     ┌───────────────────────────────────────┐
                     │        2. Multi-Provider LLM Gate     │  ◄── Groq & OpenRouter Pool,
                     │           (llm_verifier.py)           │      Zero-hallucination fail-closed,
                     └───────────────────┬───────────────────┘      Full JD & Skills extraction
                                         ▼
                     ┌───────────────────────────────────────┐
                     │     3. Storage & Deduplication        │  ◄── SQLite (pipeline_history.db),
                     │    (history_store.py / sheets_sync)   │      Live Google Sheets API sync
                     └───────────────────┬───────────────────┘
                                         ▼
                     ┌───────────────────────────────────────┐
                     │   4. Technical Interview Prediction   │  ◄── OSINT evidence scraping,
                     │      (interview_prep/ v2.0 Engine)    │      5-layer priority weighting,
                     └───────────────────┬───────────────────┘      Publication A4 PDF Dossiers
                                         ▼
                     ┌───────────────────────────────────────┐
                     │    5. Student & Recruiter Services    │  ◄── Telegram Bot, WhatsApp DPDPA,
                     │        (services/ Microservices)      │      Brevo Mailer, Student Matcher
                     └───────────────────────────────────────┘
```

---

## 2. System Architecture & Core Design Principles

1. **Terminal-First & Fail-Closed Gating**:
   * Every filtering stage defaults to rejection. If experience requirements are ambiguous or missing, the job is rejected.
   * If an LLM call fails, exhausts quotas, or returns invalid schemas, the pipeline halts or skips safely without saving corrupted data.
2. **Multi-Provider Rotating LLM Client (`RotatingLLM`)**:
   * Sequentially rotates across 3 Groq API keys (`openai/gpt-oss-120b`).
   * Automatically detects HTTP 429 (rate limits) or HTTP 403 (network blocks) and seamlessly fails over to an OpenRouter pool (`nvidia/nemotron-3-ultra-550b-a55b:free`).
3. **Deterministic Verification before Generative AI**:
   * Rule-based regex and string filters eliminate 80%+ of ineligible jobs (e.g. `2-4 years`, `Senior`, `Lead`, `Manager`, unpaid training fees) with microsecond latency before invoking LLMs.
4. **Research-Backed Interview Prediction (5-Layer Priority Scoring)**:
   * **JD Relevance (30%)**: Technologies directly mandated in the job description.
   * **Company Specialization & Projects (25%)**: Architecture patterns from company platforms, case studies, and blogs.
   * **Previous Interview Evidence (25%)**: Real questions logged on Glassdoor, AmbitionBox, and GeeksforGeeks.
   * **Employee Technical Profile Patterns (10%)**: Tech stacks reported by active engineering staff on LinkedIn.
   * **Role & Experience-Level Relevance (10%)**: Core CS fundamentals calibrated for 0–1 years of experience.
5. **Publication-Grade Document Design**:
   * Renders subtle, executive A4 PDFs using ReportLab Platypus (`#2C4152` slate accent, clean typography, dynamic two-pass page numbering `Page X of Y`, no clumsy card containers).

---

## 3. High-Level Directory Structure

```
fresher_job_scraper/
├── .github/                      # CI/CD Workflows & automated cron execution
│   ├── workflows/                # GitHub Actions definitions
│   └── last-successful-run.txt   # Automated heartbeat commit tracker
├── company_search/               # Standalone LangGraph agentic research pipeline
│   ├── results/                  # Generated research JSONs and PDF dossiers
│   └── ...                       # Agentic search, synthesis, and testing scripts
├── interview_prep/               # v2.0 Technical Interview Prediction & PDF Engine
│   ├── curator.py                # 5-layer scoring curation prompt & JSON normalizer
│   ├── drive.py                  # Google Drive automated PDF upload & link sharing
│   ├── pdf_renderer.py           # ReportLab Platypus A4 document renderer
│   ├── runner.py                 # Batch coordinator & cache orchestrator
│   └── sources.py                # Multi-engine OSINT search & excerpt extractor
├── output/                       # Local execution outputs (CSVs, JSONs, Excel, DB)
│   ├── archive/                  # Historical execution snapshots
│   └── interview_docs/           # Generated company interview dossiers (PDF + JSON)
├── services/                     # Microservices for notification, matching & outreach
│   ├── admin_alerter.py          # Real-time Telegram alerting for admins
│   ├── api.py                    # FastAPI REST server exposing scraper endpoints
│   ├── brevo_mailer.py           # Transactional recruiter email dispatcher
│   ├── db_sync.py                # SQLite to PostgreSQL replication bridge
│   ├── hr_email_templates.py     # Multi-touch outreach email templates
│   ├── master_orchestrator.py    # Multi-stage microservice coordinator
│   ├── redirect_service.py       # Telemetry link shortening & click tracker
│   ├── retention_manager.py      # Automated 12-month data retention & backups
│   ├── student_matcher.py        # Top-6 student personalized recommendation engine
│   ├── telegram_bot.py           # 24/7 interactive student placement bot
│   ├── whatsapp_client.py        # India DPDPA 2023-compliant WhatsApp dispatcher
│   ├── docker-compose.yml        # Docker stack for Postgres, Redis, and n8n
│   ├── n8n_workflow_http_*.json  # Reference n8n automation workflow
│   └── schema.sql                # Complete PostgreSQL 16 DDL relational schema
├── tests/                        # Comprehensive Pytest test suite (63 passing tests)
├── config.py                     # Central query, location, and blacklist configuration
├── excel_exporter.py             # Styled multi-tab Excel reporting engine
├── filter_engine.py              # Rule-based deterministic fresher verification engine
├── foundit_scraper.py            # Dedicated Foundit.in (Monster India) browser scraper
├── generate_interview_docs.py    # CLI entrypoint for interview document generation
├── google_sheets_sync.py         # Google Sheets API live sync and formatting
├── history_store.py              # SQLite duplicate detection & history persistence
├── hr_enricher.py                # Hiring manager & recruiter contact enrichment
├── llm_verifier.py               # Rotating LLM pool client & strict fresher gatekeeper
├── main.py                       # Main pipeline CLI orchestrator
├── requirements.txt              # Production Python package dependencies
├── test_filter.py                # Standalone filter sanity verification script
├── COVERAGE_AUDIT.md             # In-depth coverage and network bottleneck audit
├── NEXT_AGENT_HANDOFF.md         # Operational handoff guide for subsequent agents
├── PROJECT_OVERVIEW.md           # High-level mission and operational scope
└── README.md                     # Repository landing page and setup guide
```

---

## 4. File-by-File Blueprint & Technical Explanation

### 4.1 Root Core Engine Files

#### `main.py`
The primary CLI entrypoint orchestrating the end-to-end scraper pipeline. It coordinates concurrent job aggregation across JobSpy and Foundit, routes raw records through deterministic rule filtering, executes LLM verification, and synchronizes newly discovered listings with SQLite and Google Sheets. It supports operational flags such as `--quick` for diagnostic sanity sweeps and `--force` for cache bypassing.

#### `config.py`
The centralized configuration repository housing target role families, search keywords, geographic boundaries (Mumbai, Hyderabad), and supported job boards. It defines operational thresholds including maximum posting age (20h scheduled / 48h manual), result limits per query, experience ceilings (1.0 year), and extensive blacklists for excluded titles, senior levels, and known consultancy scams.

#### `scraper.py`
A high-throughput, concurrency-managed aggregation engine wrapping JobSpy across Naukri, Indeed, and LinkedIn. It implements thread-pool concurrency across sites and search queries while enforcing sequential execution on Naukri to prevent bot-detection throttles. It features a custom `EntryLevelNaukri` adapter that injects `experience=0` query parameters and inspects raw detail JSON payloads to extract structured experience fields before schema truncation.

#### `foundit_scraper.py`
A dedicated scraper for Foundit.in (formerly Monster India) engineered to bypass anti-scraping protections using `primp` and `curl_cffi` for realistic browser TLS fingerprinting. It queries Foundit's private search endpoints with fresher filters (0–1 years), isolates network errors so failed queries do not compromise the pipeline, and systematically hydrates full job descriptions to supply rich context for LLM verification.

#### `filter_engine.py`
The deterministic, zero-hallucination rule validation engine that enforces strict fresher criteria without invoking external APIs. It analyzes posting age against ISO timestamps, screens job titles against multi-word blacklists, inspects explicit numeric experience spans (e.g., `2-4 years`, `3+ yrs`), and evaluates location strings. Listings failing any check are rejected with structured audit reasons and redirected to `rejected_jobs_latest.json`.

#### `llm_verifier.py`
The intelligence gatekeeper that safeguards Google Sheets from hidden senior requirements in ambiguous job descriptions. It manages `RotatingLLM`, an automated failover pool cycling through 3 Groq API keys before falling back to OpenRouter, ensuring high uptime under strict rate limits. It extracts structured skills, validates that the job genuinely welcomes graduates with 0–1 years of experience, and fails closed if the LLM is unreachable.

#### `google_sheets_sync.py`
The live integration layer connecting the pipeline to the placement team's central Google Sheet via `gspread` and service account credentials. It performs idempotent upserts indexed by normalized Apply URLs, automatically formats header styling, applies date sorting, and manages custom columns (Title, Company, Location, Role, Date Posted, Experience, Min/Max Salary, Source, and Apply URL).

#### `excel_exporter.py`
The spreadsheet formatting engine responsible for generating executive-ready Microsoft Excel workbooks (`.xlsx`). It utilizes `openpyxl` to build multi-tab workbooks featuring styled headers, colored status badges, freeze panes, alternating row zebra striping, and auto-computed column widths for local placement reporting.

#### `history_store.py`
A persistent SQLite database manager (`output/pipeline_history.db`) that guarantees idempotency and cross-run deduplication. It hashes and indexes every processed job by title, company, and apply URL, enabling the pipeline to distinguish between repeat listings and newly discovered jobs, which are exported to `new_fresher_jobs_latest.json` for student notifications.

#### `hr_enricher.py`
A contact intelligence utility that scans job descriptions and company domains to extract recruiter and hiring manager leads. It extracts verified email patterns, recruiter names, and talent acquisition contact metadata, formatting them into `hr_leads_latest.json` for corporate relations and targeted outreach.

#### `generate_interview_docs.py`
A standalone CLI utility for generating comprehensive technical interview preparation dossiers directly from the command line. It can source target jobs directly from the live Google Sheet (e.g. `--from-sheet --company "AltissAdvance"`) or local JSON files, executing web research, LLM question curation, and ReportLab PDF compilation with detailed CLI progress bars.

#### `test_filter.py`
A lightweight root-level regression script designed for rapid local sanity testing of the filtering logic. It executes isolated checks against representative fresher and senior job descriptions to confirm that regex changes do not introduce unintended false positives or false negatives prior to running the complete test suite.

#### `requirements.txt`
The definitive Python dependency manifest specifying exact version pins for all external libraries used across the application. It encompasses scraping utilities (`python-jobspy`, `curl_cffi`, `primp`), document generation (`reportlab`, `pypdf`), data syncing (`gspread`, `openpyxl`, `google-auth`), and LLM integrations (`langchain`, `langchain-openai`, `json-repair`).

#### `.env.example`
A documented configuration template defining all required environment variables and secrets. It provides placeholders for Google Sheets configuration (`GOOGLE_SPREADSHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_FILE`), Groq API keys (`GROQ_API_KEY_1`, `2`, `3`), OpenRouter API keys (`OPENROUTER_API_KEY_1`, `2`, `3`), and optional Telegram/Brevo tokens.

#### `.gitignore`
The Git exclusion file protecting the repository from committing sensitive credentials, system caches, and generated artifacts. It strictly excludes `.env`, `credentials.json`, service account keys, `pipeline_history.db`, local test PDFs, and Python virtual environment directories (`venv/`, `__pycache__/`, `.pytest_cache/`).

#### `README.md`
The public landing page and developer setup guide for the repository. It outlines project capabilities, environment preparation steps, dependencies installation, CLI execution commands, and configuration instructions for Google Sheets authentication.

#### `PROJECT_OVERVIEW.md`
A foundational operational guide detailing the project's background, search scope, eligibility criteria, and operational boundaries. It explains the distinction between extracted and enforced fields, outlines how Naukri experience is inspected, and documents known state limitations when running on GitHub Actions.

#### `COVERAGE_AUDIT.md`
A deep technical investigation into job board scraper coverage, anti-bot behavior, and network performance. It analyzes rate-limiting responses across Naukri, LinkedIn, Indeed, and Foundit, detailing header spoofing strategies, session pooling, and optimization opportunities for production scale.

#### `NEXT_AGENT_HANDOFF.md`
A comprehensive architectural handoff document authored for incoming engineering agents and maintainers. It details the active environment state, recent architectural refactors, known edge cases, test command procedures, and strict guidelines on preserving zero-breakage across test suites.

---

### 4.2 `.github/` Automation & CI/CD

#### `.github/workflows/fresher-job-scraper.yml`
The automated GitHub Actions workflow file that executes scheduled scraper runs twice daily at 11:00 AM and 4:00 PM IST (Asia/Kolkata). It provisions a Python environment, reconstructs `credentials.json` from encrypted repository secrets, executes `main.py` with a 20-hour lookback window, updates Google Sheets, and pushes a lightweight heartbeat commit.

#### `.github/last-successful-run.txt`
A small timestamp tracking file committed automatically by the GitHub Actions workflow upon the successful conclusion of a scrape run. It serves as an automated heartbeat that prevents GitHub from deactivating scheduled Actions due to 60 days of repository inactivity.

---

### 4.3 `interview_prep/` Subsystem (v2.0 Technical Interview Prediction & A4 PDF Engine)

#### `interview_prep/__init__.py`
The package initialization file that defines the public API of the interview preparation subsystem. It cleanly exposes primary entry points—`build_interview_pack`, `render_interview_pdf`, and `generate_interview_prep_for_jobs`—ensuring loose coupling between the runner and downstream PDF/LLM components.

#### `interview_prep/runner.py`
The orchestration engine that drives batch interview document generation across multiple jobs. It loads target listings from Google Sheets or local JSON, computes deterministic SHA-256 cache keys to avoid redundant LLM invocations, triggers OSINT web intelligence collection, invokes the curator, saves `questions.json`/`meta.json`, and triggers PDF rendering.

#### `interview_prep/curator.py`
The master LLM prompting and schema validation module operating under the "Deep Company Research & Technical Interview Prediction" methodology. It enforces the 5-layer priority scoring model (JD 30%, Company 25%, Interview 25%, Profiles 10%, Fresher 10%) to synthesize exactly 15–20 questions categorized by Topic, Evidence Class (`A/B/C/D`), Likelihood (`Very High/High/Medium`), concise bulleted answers, practical examples, and formatted code blocks with algorithmic complexity.

#### `interview_prep/pdf_renderer.py`
A publication-quality PDF generator built using ReportLab's Platypus framework that compiles curated interview packs into elegant A4 portrait documents. It implements a custom two-pass `NumberedCanvas` for exact `Page X of Y` footers, applies a professional `#2C4152` dark slate visual theme, formats multi-line executive summary boxes, and renders clean code blocks and bullet points without awkward card borders.

#### `interview_prep/sources.py`
The OSINT research module that scours the public web for real interview experiences and engineering stack details. It queries search providers (DuckDuckGo, Yahoo, Startpage, Yandex) across approved domains (GeeksforGeeks, AmbitionBox, Glassdoor, LeetCode, company engineering blogs), cleaning legal corporate suffixes (e.g., stripping `Private Limited`) and extracting contextual text snippets for LLM synthesis.

#### `interview_prep/drive.py`
An automated cloud storage integration module interfacing with the Google Drive API. It handles creating target directories, uploading rendered PDF interview dossiers with public read permissions, and returning shareable web view links that are automatically embedded into the placement team's Google Sheet.

---

### 4.4 `company_search/` Subsystem (Dynamic Agentic Dossier Research)

#### `company_search/README.md`
A dedicated guide documenting the architecture and CLI usage of the LangGraph-powered company research subsystem. It explains the multi-source intelligence gathering methodology, token batching strategies, Pydantic schema constraints, and instructions for generating on-the-spot company dossiers.

#### `company_search/agentic_pipeline.py`
A state-machine pipeline built on LangGraph that orchestrates multi-step company intelligence synthesis. It manages state transitions between web searching, context extraction, token-bounded batching, and LLM reasoning, ensuring that large volumes of scraped blog posts and interview reviews do not overflow model context windows.

#### `company_search/dynamic_search.py`
A targeted crawling module that performs focused queries against trusted career portals and engineering repositories. It incorporates polite scraping mechanisms via `httpx`, checking `robots.txt` compliance, honoring rate limits, and parsing HTML into structured text excerpts.

#### `company_search/pdf_generator.py`
A dedicated ReportLab PDF compiler tailored for executive company intelligence dossiers. It structures data into comprehensive sections covering Executive Profiles, Flagship Case Studies, Architectural Patterns, STAR-method Behavioral Playbooks, and Technical Deep Dives with interviewer trap callouts.

#### `company_search/run_research.py`
The command-line runner enabling instant research for any company and role combination (e.g. `python company_search/run_research.py --company "Google" --role "SDE1"`). It validates environment credentials, initializes the agentic graph, executes dynamic web research, and outputs both structured JSON and a styled PDF dossier.

#### `company_search/source_catalog.json`
A curated domain whitelist that restricts web research to authoritative career and technical platforms. It indexes trusted interview repositories (GeeksforGeeks, AmbitionBox, PrepInsta, InterviewExperiences.in) and engineering publication hubs, preventing the pipeline from processing low-quality content farms.

#### `company_search/test_dynamic_agentic.py`
An automated test suite validating the stability and resilience of the `company_search` pipeline. It verifies that token chunking correctly splits large documents, confirms strict failure policies when API keys are missing, tests `json_repair` fallback parsing, and ensures valid Pydantic serialization.

#### `company_search/requirements.txt`
A specialized dependency manifest specifying packages required by the LangGraph agentic pipeline. It includes `langgraph`, `langchain-core`, `pydantic`, `httpx`, and ReportLab dependencies required for running the company research subsystem independently.

#### `company_search/results/.gitkeep`
A tracking placeholder file ensuring that the `company_search/results/` directory is retained in Git version control, providing an output directory for generated dossier artifacts.

---

### 4.5 `services/` Subsystem (Prototypes & Downstream Distribution)

#### `services/README.md`
The architectural specification for the placement microservices ecosystem. It provides an overview of prototypes designed for student matching, multi-channel distribution (WhatsApp, Telegram, Email), relational database auditing, and containerized deployment.

#### `services/__init__.py`
The module initialization file that marks the `services/` directory as an importable Python package, enabling cross-service imports between the orchestrator, student matcher, and messaging clients.

#### `services/master_orchestrator.py`
A comprehensive coordinator prototype illustrating an enterprise end-to-end placement workflow. It links job ingestion, database syncing to PostgreSQL, running student recommendation matching algorithms, dispatching Telegram/WhatsApp notifications, and triggering HR email campaigns.

#### `services/api.py`
A lightweight REST API service developed with FastAPI. It exposes HTTP endpoints (e.g., `/api/v1/trigger-scrape`, `/api/v1/jobs/latest`, `/api/v1/match-student`) that allow external automation engines, webhooks, or n8n workflows to trigger scraper runs and query processed listings.

#### `services/student_matcher.py`
A multi-factor matching engine that pairs verified fresher jobs with registered student profiles. It calculates a weighted affinity score based on technical skills overlap, preferred job locations, role tracks, and graduation year eligibility, generating personalized top-6 opportunity digests for each student.

#### `services/whatsapp_client.py`
A simulated WhatsApp delivery client engineered to comply with the Indian Digital Personal Data Protection Act (DPDPA 2023). It manages candidate opt-in/opt-out consent tracking, generates compliant transactional job alert templates, and enforces daily messaging frequency caps.

#### `services/telegram_bot.py`
An interactive 24/7 Telegram bot built using long-polling for real-time student engagement. It enables students to execute slash commands (e.g., `/jobs`, `/filter`, `/prep`), browse recently scraped fresher roles, and download generated interview preparation PDFs directly within chat.

#### `services/brevo_mailer.py`
An automated transactional email dispatcher integrating with the Brevo (formerly Sendinblue) REST API. It handles transactional SMTP delivery, tracks email opens/clicks, and dispatches customized cold outreach sequences and interview requests to verified HR contacts.

#### `services/hr_email_templates.py`
A repository of responsive, professionally copywritten HTML and plain-text email templates. It includes multi-touch candidate introduction emails, placement partnership proposals, and job application letters calibrated for corporate recruiters and talent acquisition leads.

#### `services/db_sync.py`
A data synchronization utility that bridges the local SQLite database (`pipeline_history.db`) with an enterprise PostgreSQL 16 relational database. It ensures transactional integrity, replicates newly verified jobs and application events, and handles schema version migrations.

#### `services/retention_manager.py`
A maintenance utility enforcing a strict 12-month data lifecycle and retention policy. It automatically purges expired job listings, rotates historical audit logs, compresses stale records into cold storage, and generates automated database backups.

#### `services/admin_alerter.py`
An operational alerting module that notifies system administrators via Telegram upon critical pipeline failures. It monitors execution heartbeats, catches unhandled exceptions, and alerts on scraper IP blocks, API quota exhaustion, or Google Sheets sync errors.

#### `services/redirect_service.py`
A link-shortening and click-tracking microservice that generates obfuscated redirect tokens for job application URLs. It logs student click telemetry, tracking which job boards and roles receive the highest student engagement while preventing direct URL scraping.

#### `services/schema.sql`
A complete PostgreSQL 16 relational DDL schema defining the enterprise database architecture. It specifies tables, foreign keys, and indexes for `jobs`, `companies`, `students`, `skills`, `matches`, `applications`, `hr_contacts`, and `audit_logs`.

#### `services/docker-compose.yml`
A container orchestration definition for local and production deployment. It provisions a multi-container stack comprising PostgreSQL 16 (with persistent volumes), Redis (for task queuing and rate limiting), and an n8n workflow automation service.

#### `services/n8n_workflow_http_google_sheets.json`
An exportable n8n workflow template configured to listen for HTTP webhooks from `services/api.py`. It automates secondary downstream workflows, formatting scraped job payloads and routing alerts to external Slack or Google Sheets channels.

---

### 4.6 `tests/` Test Suite (63 / 63 Unit & Regression Tests)

#### `tests/__init__.py`
Package initialization file making the `tests/` directory discoverable by Pytest and enabling shared fixtures across test modules.

#### `tests/test_filter.py`
Legacy unit test suite verifying core string normalization, basic role categorization, posting date freshness calculations, and title/company blacklist filtering.

#### `tests/test_filter_engine.py`
The comprehensive 33-test suite for `filter_engine.py`. It rigorously evaluates numeric experience boundaries (0–1 yr pass, 2–4 yr fail), LinkedIn missing-experience fallbacks, apply URL domain validation, location matching, and specific edge-case regressions reported during live runs.

#### `tests/test_foundit_scraper.py`
A dedicated test suite validating the Foundit / Monster India scraper. It tests browser header emulation, API response parsing, HTML description hydration, error isolation under network timeouts, and seamless pass-through into the filter engine.

#### `tests/test_llm_verifier.py`
The security and verification test suite for `llm_verifier.py`. It confirms that the gatekeeper strictly fails closed when API keys are absent or network errors occur, verifies requirements extraction, and tests multi-key rotating failover across Groq and OpenRouter.

#### `tests/test_interview_prep.py`
The test suite for the `interview_prep/` subsystem. It verifies JSON pack normalization, ensures question counts strictly honor limits (15–20 questions, at most 2 answered coding problems), tests approved host filtering, and confirms ReportLab generates structurally valid PDF binaries.

#### `tests/test_company_research.py`
The test suite for the `company_search/` agentic pipeline. It tests domain catalog validation, token batching chunkers, Pydantic schema constraints, error handling on missing LLM credentials, and diagnostic JSON extraction.

---

## 5. Output Data Formats & Cache Stores

### 5.1 Local Run Outputs (`output/`)
* **`fresher_jobs_latest.csv` / `.json` / `.xlsx`**: The canonical dataset of all verified, active fresher jobs from the most recent run.
* **`fresher_jobs_<TIMESTAMP>.csv` / `.json` / `.xlsx`**: Immutable historical run snapshots stored for archival and trend analysis.
* **`new_fresher_jobs_latest.json`**: The differential list of brand-new jobs discovered in the latest run that do not exist in the historical database.
* **`rejected_jobs_latest.json`**: Comprehensive audit log containing every rejected job, its raw metadata, and the exact rule that triggered rejection.
* **`hr_leads_latest.json`**: Enriched contact details for recruiters and talent acquisition leads extracted from verified job postings.
* **`pipeline_history.db`**: Local SQLite database storing SHA-256 hashes of all previously processed jobs to prevent duplicate processing.

### 5.2 Interview Preparation Dossiers (`output/interview_docs/`)
For each researched company and role, a dedicated subfolder is created:
`output/interview_docs/<COMPANY_SLUG>_<ROLE_SLUG>/`
* **`<COMPANY>_<ROLE>_Interview_Prep.pdf`**: The publication-ready, 6-page A4 PDF formatted with dark slate `#2C4152` styling, executive summary, 20 evidence-backed questions, code snippets with Big-O complexity, and page numbers.
* **`questions.json`**: Full structured JSON payload containing the complete question pack, evidence ratings, answer bullets, examples, and source citations.
* **`meta.json`**: Cache metadata storing the job cache key, timestamp, question count, and Google Drive upload URL.

---

## 6. Verification & Test Execution

The platform enforces a strict **zero-breakage rule**. All 63 automated tests must pass before any changes are committed or deployed.

```powershell
# Execute the complete automated test suite:
pytest fresher_job_scraper/tests -v

# Run with test coverage summary:
pytest fresher_job_scraper/tests --durations=10

# Execute specific test modules:
pytest fresher_job_scraper/tests/test_filter_engine.py -v
pytest fresher_job_scraper/tests/test_llm_verifier.py -v
pytest fresher_job_scraper/tests/test_interview_prep.py -v
```

---

## 7. Command Reference Quick-Sheet

| Task | Command |
|---|---|
| **Standard Full Scrape** | `python main.py` |
| **Diagnostic Quick Sweep** | `python main.py --quick` |
| **Bypass Deduplication Cache** | `python main.py --force` |
| **Generate Interview Dossiers from Sheet** | `python generate_interview_docs.py --from-sheet` |
| **Generate Dossier for Specific Company** | `python generate_interview_docs.py --from-sheet --company "AltissAdvance" --force` |
| **Run On-the-Spot Company Research** | `python company_search/run_research.py --company "Amazon" --role "Data Analyst"` |
| **Run Test Suite** | `pytest fresher_job_scraper/tests -v` |
