"""Evaluation Dataset Builder representing Ground Truth Test Cases."""
from __future__ import annotations

from typing import List, Tuple
from models.opportunity import Opportunity, OpportunityType
from models.verification_result import VerificationDecision

BENCHMARK_CASES: List[Tuple[Opportunity, VerificationDecision, str]] = [
    # CASE 1: Graduate recruitment program accepting 2026/2027 graduates, no contradictory exp
    (
        Opportunity(
            id="bench_case_1",
            opportunity_type=OpportunityType.OFF_CAMPUS_DRIVE,
            title="TCS National Qualifier Test (NQT) 2026",
            normalized_title="TCS National Qualifier Test (NQT) 2026",
            company="Tata Consultancy Services",
            location="Pan India",
            description="TCS NQT is opening for 2026 and 2027 batch B.E/B.Tech/MCA/M.Sc graduates. Direct hiring into Ninja and Digital roles.",
            eligible_batches=["2026", "2027"],
            source_id="campusdrive",
            listing_url="https://campusdrive.in/tcs-nqt-2026",
            apply_url="https://www.tcs.com/careers/india/tcs-national-qualifier-test",
            discovered_at="2026-11-17T00:00:00",
        ),
        VerificationDecision.ACCEPTED,
        "Case 1: Standard graduate recruitment drive with valid target batches",
    ),

    # CASE 2: 2026 batch mentioned, but demands 3 years of commercial experience
    (
        Opportunity(
            id="bench_case_2",
            opportunity_type=OpportunityType.INDIVIDUAL_FRESHER_JOB,
            title="Software Engineer - Full Stack (2026 Eligible)",
            normalized_title="Software Engineer - Full Stack",
            company="TechCorp Solutions",
            location="Bangalore",
            description="We welcome 2026 batch candidates. Minimum 3 years of professional experience in React and Node.js required in production environments.",
            eligible_batches=["2026"],
            source_id="jobs4fresher",
            listing_url="https://jobs4fresher.com/techcorp-software-engineer",
            apply_url="https://techcorp.example.com/careers/apply",
            discovered_at="2026-11-17T00:00:00",
        ),
        VerificationDecision.REJECTED,
        "Case 2: Experience contradiction (invites batch but demands 3 years experience)",
    ),

    # CASE 3: Graduate trainee position with no explicit experience field targeting university grads
    (
        Opportunity(
            id="bench_case_3",
            opportunity_type=OpportunityType.INDIVIDUAL_FRESHER_JOB,
            title="Graduate Engineer Trainee (GET)",
            normalized_title="Graduate Engineer Trainee",
            company="L&T Technology Services",
            location="Vadodara",
            description="Seeking dynamic university campus graduates for our 12-month engineering trainee program. Comprehensive technical mentoring provided.",
            eligible_batches=["2025", "2026"],
            source_id="elitmus",
            listing_url="https://www.elitmus.com/jobs/lnt-get",
            apply_url="https://www.elitmus.com/jobs/lnt-get/apply",
            discovered_at="2026-11-17T00:00:00",
        ),
        VerificationDecision.ACCEPTED,
        "Case 3: Genuine graduate trainee position without explicit numeric exp field",
    ),

    # CASE 4: Senior software engineer position with missing experience information
    (
        Opportunity(
            id="bench_case_4",
            opportunity_type=OpportunityType.INDIVIDUAL_FRESHER_JOB,
            title="Senior Principal Software Architect",
            normalized_title="Senior Principal Software Architect",
            company="Enterprise Cloud Systems",
            location="Hyderabad",
            description="Lead architectural strategy, distributed consensus algorithms, and multi-region infrastructure governance.",
            eligible_batches=[],
            source_id="useastra",
            listing_url="https://www.useastra.in/jobs/senior-architect",
            apply_url="https://enterprisecloud.example.com/jobs/99",
            discovered_at="2026-11-17T00:00:00",
        ),
        VerificationDecision.REJECTED,
        "Case 4: Senior role without experience information must NOT be approved",
    ),

    # CASE 5: Generic off-campus drive accepting 2026/2027 graduates without tech-specific role
    (
        Opportunity(
            id="bench_case_5",
            opportunity_type=OpportunityType.OFF_CAMPUS_DRIVE,
            title="Cognizant GenC Off-Campus Recruitment Drive",
            normalized_title="Cognizant GenC Off-Campus Recruitment Drive",
            company="Cognizant",
            location="Pan India",
            description="Cognizant invites 2026 and 2027 graduates for GenC multi-stream recruitment across consulting, development, and infrastructure.",
            eligible_batches=["2026", "2027"],
            source_id="saarthi_drives",
            listing_url="https://joinsaarthi.com/drives/genc-2026",
            apply_url="https://app.joinsuperset.com/cognizant/genc",
            discovered_at="2026-11-17T00:00:00",
        ),
        VerificationDecision.ACCEPTED,
        "Case 5: Generic collective off-campus drive preserved and accepted",
    ),

    # CASE 6: Fee-charging training scam masquerading as fresher drive
    (
        Opportunity(
            id="bench_case_6",
            opportunity_type=OpportunityType.OFF_CAMPUS_DRIVE,
            title="Freshers Mega Hiring Drive 2026",
            normalized_title="Freshers Mega Hiring Drive 2026",
            company="Apex Career Solutions",
            location="Noida",
            description="Immediate placement for freshers. Mandatory refundable registration fee of Rs 2500 required before interview scheduling.",
            eligible_batches=["2026"],
            source_id="freshersdunia",
            listing_url="https://freshersdunia.in/apex-hiring-drive",
            apply_url="https://freshersdunia.in/apex-apply",
            discovered_at="2026-11-17T00:00:00",
        ),
        VerificationDecision.REJECTED,
        "Case 6: Fraudulent listing demanding upfront registration fee",
    ),
]


def get_benchmark_dataset() -> List[Tuple[Opportunity, VerificationDecision, str]]:
    """Returns the ground truth benchmark suite."""
    return BENCHMARK_CASES
