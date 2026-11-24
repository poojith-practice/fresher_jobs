"""Production configuration for the Fresher Job Scraper pipeline."""

MAX_HOURS_OLD = 48
TARGET_SITES = ["freshersdunia", "campusdrive", "naukri", "indeed", "linkedin", "monsterindia"]
UNSUPPORTED_SITES = []
DEFAULT_LOCATIONS = [
    "Bangalore", "Hyderabad", "Pune", "Mumbai", "Gurgaon", "Noida", "Chennai"
]
INDEED_COUNTRY = "india"
RESULTS_PER_QUERY = 25
QUERY_DELAY_SECONDS = 1.0
QUERY_CONCURRENCY = 3
JOBSPY_PROXIES = []
MAX_ALLOWED_EXPERIENCE_YEARS = 1.0

ROLE_QUERIES = {
    "Business Analyst": ["business analyst", "junior business analyst", "business analyst fresher"],
    "Data Analyst": ["data analyst", "junior data analyst", "data analyst fresher"],
    "Marketing Analyst": ["marketing analyst", "junior marketing analyst", "marketing analyst fresher"],
    "HR Analyst": ["HR analyst", "junior HR analyst", "HR analyst fresher"],
    "Analyst": ["analyst", "junior analyst", "trainee analyst", "analyst fresher"],
    "Full Stack Developer": ["full stack developer", "junior full stack developer", "full stack developer fresher", "associate software engineer", "software engineer trainee"],
    "Web Developer": ["web developer", "junior web developer", "web developer fresher", "frontend developer fresher", "react developer fresher"],
    "Software Engineer": ["software engineer fresher", "junior software engineer", "associate software engineer", "graduate engineer trainee", "junior software developer", "entry level software engineer"],
}

# Forbidden title keywords (indicates senior / experienced / non-fresher / non-IT roles)
# Note: Numeric experience ranges like '5+ years' are handled specifically via regex
# in filter_engine.py to prevent false positives on salaries (e.g. '8.5 LPA') or '5S'.
FORBIDDEN_TITLE_KEYWORDS = [
    "senior", "sr", "lead", "leader", "principal", "architect",
    "manager", "head", "director", "vp", "vice president", "specialist",
    "chief", "staff engineer", "expert", "consultant 2", "mid-level",
    "mid level", "level 2", "level 3", "years experience",
    # Strictly forbid QA, Testing, Mechanical, Civil, CAD, and non-software engineering disciplines
    "qa", "qc", "tester", "testing", "quality assurance", "quality control",
    "quality analyst", "quality engineer", "sdet", "test engineer",
    "autocad", "cad", "mechanical", "civil", "electrical engineer",
    "site engineer", "manufacturing", "mfg", "inspector", "hardware",
    # Strictly forbid factory, plant, shift operator, diploma, technician, field roles
    "diploma", "shift operator", "operator", "technician", "plant", "maintenance",
    "field engineer", "field operator", "water systems", "water treatment", "welder",
    "fitter", "machinist", "electrician", "telecaller", "telemarketing", "bpo",
    "call center", "customer support executive", "customer care executive"
]

FORBIDDEN_JOB_LEVELS = ["mid_senior", "director", "executive", "associate_director"]

COMPANY_BLACKLIST = [
    "internshala", "unacademy", "byjus", "byju's", "whitehat jr", "vedantu",
    "toppr", "upgrad", "upgrade", "simplilearn", "edureka", "intellipaat",
    "great learning", "scaler", "newton school", "alma better", "almabetter",
    "masai school", "coding ninjas", "geekster", "acciojob", "crio.do",
    "qspiders", "jspiders", "pyspiders", "naresh i technologies", "naresh it",
    "durga software", "durga soft", "besant technologies", "apponix",
    "ethnus", "kelly technologies", "sla consultants", "croma campus",
    "sevenmentor", "fita academy", "cetpa", "actalent training",
    "training institute", "coaching institute", "it academy",
    "learning solutions", "skills academy", "training center",
    "training centre", "finishing school", "placement guarantee",
    "job guarantee", "hire and train", "train and hire",
    "edtech", "edutech"
]

FORBIDDEN_DESCRIPTION_PATTERNS = [
    "registration fee", "training fee", "security deposit",
    "pay after placement", "unpaid internship", "unpaid intern",
    "no stipend", "commission only", "earn from home data entry",
    "sms sending job", "part time form filling", "captcha typing"
]
