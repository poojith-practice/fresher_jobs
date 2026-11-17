"""Offline Mock Fixtures for Unit Testing Coverage Lab Components."""

MOCK_SAARTHI_HTML = """
<!DOCTYPE html>
<html>
<head><title>Saarthi Drives</title></head>
<body>
<script id="__NEXT_DATA__" type="application/json">
{
  "props": {
    "pageProps": {
      "initialDrives": [
        {
          "id": "mock-drive-uuid-1",
          "drive_name": "Amazon Off Campus Drive 2026: SDE-1",
          "description": "Amazon is hiring fresh 2026 graduates for SDE-1 roles.",
          "eligibility_criteria": "B.Tech/MCA 2026 batch with no active backlogs.",
          "start_date": "2026-11-01",
          "end_date": "2026-11-30",
          "isDriveEnded": false,
          "ctc_min": 1400000,
          "ctc_max": 2200000,
          "company": {"name": "Amazon India"},
          "locations": ["Bangalore", "Hyderabad"]
        },
        {
          "id": "mock-drive-uuid-2",
          "drive_name": "Closed Enterprise Drive 2025",
          "description": "Old hiring drive concluded.",
          "eligibility_criteria": "2025 batch",
          "isDriveEnded": true,
          "company": {"name": "OldCo"}
        }
      ]
    }
  }
}
</script>
</body>
</html>
"""

MOCK_CAMPUSDRIVE_HTML = """
<html>
<body>
  <div class="job-card">
    <a href="/tata-communications-off-campus-drive">Tata Communications Off Campus Drive 2026: Software Engineer | Apply</a>
    <a href="https://api.whatsapp.com/send?text=Role%3A%20Software%20Engineer%0ABatch%3A%202026%20Passing%20Out%0APackage%3A%206%20LPA%0ALocation%3A%20Pan%20India">WhatsApp Share</a>
  </div>
</body>
</html>
"""

MOCK_ELITMUS_HTML = """
<html>
<body>
  <div class="job-item">
    <a href="/jobs/33259-elitmus-evaluation-software-developer-associate-consultant-bangalore">Software Developer/Associate consultant</a>
    <div>Salary: 6.0 LPA | Bangalore | Fresher</div>
  </div>
</body>
</html>
"""

MOCK_AMAZON_JSON = {
    "jobs": [
        {
            "id": "AMZN-JOB-1",
            "title": "Software Development Engineer - 2026 Grad",
            "city": "Hyderabad",
            "posted_date": "November 15, 2026",
            "job_path": "/jobs/AMZN-JOB-1",
            "description": "Amazon is seeking graduates for Software Development Engineer roles.",
            "basic_qualifications": "Enrolled in Bachelor's or Master's degree in CS graduating in 2026."
        }
    ]
}
