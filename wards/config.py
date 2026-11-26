"""Configuration, policy loading and validation, and environment secret access."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPORT_SCHEMA = "raksha-report/1"
SUPPORTED_EXTENSIONS = (".csv", ".tsv", ".json", ".txt")
RSS_SAMPLE_INTERVAL_SEC = 0.05
DEFAULT_POLICY_PATH = Path(__file__).resolve().parent.parent / "config" / "policy.yaml"
NUMERIC_REDACTION_SENTINEL = 0

PLACEHOLDERS: dict[str, str] = {
    "PATIENT_NAME": "[PATIENT_NAME]",
    "RELATIVE": "[RELATIVE]",
    "PHONE": "[PHONE]",
    "EMAIL": "[EMAIL]",
    "AADHAAR": "[AADHAAR]",
    "AADHAAR_MASKED": "[AADHAAR_MASKED]",
    "ABHA": "[ABHA]",
    "ABHA_ADDRESS": "[ABHA_ADDRESS]",
    "PAN": "[PAN]",
    "MRN": "[MRN]",
    "INSURANCE": "[INSURANCE]",
    "DOB": "[DOB]",
    "VILLAGE": "[VILLAGE]",
    "LOCALITY": "[LOCALITY]",
    "HOUSE": "[HOUSE]",
    "LANDMARK": "[LANDMARK]",
    "PIN": "[PIN]",
    "ADDRESS": "[ADDRESS]",
    "AGE": "[AGE]",
}

# Filename-safe placeholders (no / \ : * ? " < > | or brackets)
FILENAME_PLACEHOLDERS: dict[str, str] = {kind: token.strip("[]") for kind, token in PLACEHOLDERS.items()}

# Named windows and shared R7/R8 linguistic constants (MISTAKES #32)
KCO_HO_WINDOW_CHARS = 80
PRE_REL_LOOKBACK_CHARS = 80
DEVA_TIME_UNITS = ("दिन", "सप्ताह", "माह", "महीने", "वर्ष")
DEVA_SYMPTOM_WORDS = (
    "बुखार",
    "दर्द",
    "खांसी",
    "जुकाम",
    "कमजोरी",
    "चक्कर",
    "उल्टी",
    "दस्त",
    "सूजन",
    "सांस",
)
HINGLISH_SUBJECT_MARKERS = (
    "BP",
    "pulse",
    "temp",
    "spo2",
    "RBS",
    "Hb",
    "condition",
    "tabiyat",
    "halat",
    "bukhar",
    "dard",
    "report",
    "weight",
)
DOCUMENT_SUBJECT_NOUNS = ("summary", "record", "report", "note", "visit", "case")
ATTENDANT_ACTION_VERBS = (
    "accompanied",
    "brought",
    "witnessed",
    "attended",
    "signed",
    "called",
    "contacted",
    "informed",
    "reported",
)
REFERRAL_CLINICAL_VERBS = ("accompanied", "brought", "witnessed", "attended", "referred", "reviewed")

# R9 hidden-channel cleaning constants (generic formats/function words only; D6 ratchet-compliant)
MIN_CHANNEL_NAME_TOKEN_LEN = 3
MIN_CHANNEL_MRN_DIGITS = 5
CHANNEL_SAFE_WORDS = frozenset(
    {
        "com",
        "csv",
        "fhir",
        "jpg",
        "json",
        "patient",
        "patients",
        "pdf",
        "root",
        "tsv",
        "txt",
        "version",
        "xml",
        "by",
        "of",
        "for",
        "and",
        "the",
        "name",
        "names",
    }
)
METADATA_PATH_KEY_TOKENS = frozenset(
    {
        "source",
        "path",
        "file",
        "filename",
        "filepath",
        "uri",
        "url",
        "href",
        "src",
        "export",
        "exported",
        "dir",
        "folder",
        "location",
        "origin",
    }
)

# R9 base64 channel detection, nesting, and fail-closed redaction constants
# Arbitrarily short non-attachment strings (<12 chars) are skipped in plain JSON to avoid false positives;
# explicit attachments and data: URIs decode from >=2 base64 chars regardless of length.
BASE64_MIN_LEN = 12
BASE64_MIN_EXPLICIT_LEN = 2
BASE64_MIN_PRINTABLE_RATIO = 0.85
BASE64_MAX_DEPTH = 3
BASE64_MIME_LINE_WIDTH = 76
BASE64_MAX_WRAP_WIDTH = 256
DATA_URI_PREFIX = "data:"
DATA_URI_MIN_LEN = 13
BASE64_PLACEHOLDER = "[DATA_REDACTED]"
BASE64_BINARY_REASON = "base64_binary_redacted"
BASE64_INVALID_REASON = "base64_invalid_redacted"
BASE64_DEPTH_REASON = "base64_depth_exceeded"

# R5 structured column value-shape voting thresholds (bounded O(cap * cols))
COLUMN_VOTE_SAMPLE_CAP = 200
COLUMN_VOTE_MIN_RATIO = 0.5
# Minimum distinct-value share of non-empty sampled cells required for an ID-shaped column to override
# a PRESERVE_EXACT/facility header (low-cardinality repeated facility/department codes stay preserved).
COLUMN_ID_MIN_CARDINALITY_RATIO = 0.5
# A column/key-level ID decision needs at least this many values: one value carries no
# cardinality evidence (1 distinct of 1), so it never overrides the header meaning.
COLUMN_ID_MIN_VALUES = 2
# A large column with repeat visits has a low distinct share but many distinct values; this many
# distinct ID-shaped values is enough on its own (above the size of a facility/department code set).
COLUMN_ID_MIN_DISTINCT = 10
COLUMN_NAME_MAX_TOKENS = 5

# Patient-ID slot priorities (wards/slots.py): primary meaning wins, then secondary, then shape vote.
SLOT_PRIORITY_EXCLUDED = -1
SLOT_PRIORITY_NEUTRAL = 0
SLOT_PRIORITY_PRIMARY = 1
SLOT_PRIORITY_SECONDARY = 2

# Generic R7/R8 linguistic constants (never harvested from dev inputs)
NAME_LABELS = (
    "Patient Name",
    "Pt. Name",
    "Pt Name",
    "Patient's Name",
    "Name",
    "Naam",
    "Mareez ka Naam",
    "Mareez",
    "Patient",
    "Pt",
    "Attendant",
    "मरीज़ का नाम",
    "मरीज का नाम",
    "रोगी का नाम",
    "नाम",
    "मरीज़",
    "मरीज",
    "रोगी",
)

RELATIVE_LABELS = (
    "Relative Name",
    "Guardian Name",
    "Guardian",
    "Father Name",
    "Father's Name",
    "Husband Name",
    "Husband's Name",
    "Mother Name",
    "Spouse Name",
    "Next of Kin",
    "पिता का नाम",
    "पति का नाम",
    "माता का नाम",
    "अभिभावक",
)

NAME_LABEL_STOP_WORDS = frozenset(
    {
        "age",
        "umar",
        "umra",
        "aayu",
        "ayu",
        "sex",
        "gender",
        "ling",
        "dob",
        "birth",
        "janm",
        "uhid",
        "reg",
        "registration",
        "ipd",
        "opd",
        "mrn",
        "cr",
        "mob",
        "mobile",
        "phone",
        "tel",
        "address",
        "addr",
        "pata",
        "gram",
        "gaon",
        "village",
        "mohalla",
        "tehsil",
        "district",
        "jila",
        "pin",
        "date",
        "tarikh",
        "tithi",
        "ward",
        "bed",
        "consultant",
        "doctor",
        "dr",
        "abha",
        "aadhaar",
        "aadhar",
        "pan",
        "email",
        "diagnosis",
        "complaints",
        "history",
        "father",
        "mother",
        "husband",
        "wife",
        "spouse",
        "guardian",
        "relative",
        "pita",
        "pati",
        "mata",
        "name",
        "naam",
        "आयु",
        "उम्र",
        "लिंग",
        "जन्म",
        "पता",
        "ग्राम",
        "गाँव",
        "गांव",
        "मोहल्ला",
        "तहसील",
        "जिला",
        "पिन",
        "तारीख",
        "तिथि",
        "दिनांक",
        "पंजीकरण",
        "आईपीडी",
        "ओपीडी",
        "मोबाइल",
        "फ़ोन",
        "फोन",
        "ईमेल",
        "आधार",
        "पिता",
        "पति",
        "माता",
        "अभिभावक",
        "नाम",
        "डॉक्टर",
        "निदान",
    }
)

PREFIX_HONORIFICS = (
    "Shri",
    "Shree",
    "Smt.",
    "Smt",
    "Kumari",
    "Km.",
    "Mr.",
    "Mr",
    "Mrs.",
    "Mrs",
    "Ms.",
    "Ms",
    "Master",
    "Baby",
    "Late",
    "श्री",
    "श्रीमती",
    "सुश्री",
    "कुमारी",
    "मास्टर",
)

SUFFIX_HONORIFICS = (
    "ji",
    "babu",
    "sahab",
    "saheb",
    "didi",
    "bhaiya",
    "bhai",
    "behenji",
    "bahanji",
    "chachu",
    "chacha",
    "chachi",
    "mama",
    "mami",
    "papa",
    "mummy",
    "dada",
    "dadi",
    "nana",
    "nani",
    "bua",
    "mausi",
    "mausa",
    "kaka",
    "kaki",
    "tau",
    "tai",
    "taya",
    "phupha",
    "uncle",
    "aunty",
    "जी",
    "बाबू",
    "साहब",
    "साहेब",
    "दीदी",
    "भैया",
    "भाई",
    "बहनजी",
    "मामा",
    "मामी",
    "चाचू",
    "चाचा",
    "चाची",
    "पापा",
    "मम्मी",
    "दादा",
    "दादी",
    "नाना",
    "नानी",
    "बुआ",
    "मौसी",
    "काका",
    "ताऊ",
)

COMPLAINT_WORDS = frozenset(
    {
        "fever",
        "cough",
        "pain",
        "cold",
        "weakness",
        "headache",
        "vomiting",
        "diarrhoea",
        "diarrhea",
        "breathlessness",
        "dyspnea",
        "dyspnoea",
        "chest",
        "abdominal",
        "abdomen",
        "body",
        "joint",
        "swelling",
        "rash",
        "itching",
        "dizziness",
        "vertigo",
        "burning",
        "bleeding",
        "lethargy",
        "anorexia",
        "nausea",
        "chills",
        "rigors",
        "palpitations",
        "insomnia",
        "loose",
        "stools",
        "hematuria",
        "dysuria",
        "backache",
        "sob",
        "giddiness",
        "fatigue",
        "malaise",
        "sore",
        "throat",
        "injury",
        "trauma",
        "fall",
        "burn",
        "fracture",
        "seizure",
        "syncope",
        "edema",
        "oedema",
        "generalised",
        "generalized",
        "acute",
        "chronic",
        "high",
        "grade",
        "low",
        "mild",
        "moderate",
        "severe",
        "persistent",
        "recurrent",
        "productive",
        "dry",
        "bukhar",
        "dard",
        "khansi",
        "jukam",
        "zukam",
        "kamzori",
        "chakkar",
        "ultee",
        "ulti",
        "dast",
        "saans",
        "sujan",
        "jalan",
        "बुखार",
        "दर्द",
        "खांसी",
        "जुकाम",
        "कमजोरी",
        "चक्कर",
        "उल्टी",
        "दस्त",
        "सूजन",
        "सांस",
        "जलन",
        "चोट",
        "घबराहट",
        "बेहोशी",
    }
)

CLINICAL_HEAD_NOUNS = frozenset(
    {
        "disease",
        "syndrome",
        "palsy",
        "lymphoma",
        "carcinoma",
        "leukemia",
        "anaemia",
        "anemia",
        "sign",
        "reflex",
        "triad",
        "test",
        "score",
        "scale",
        "fracture",
        "fever",
        "cholera",
        "malaria",
        "typhoid",
        "diabetes",
        "hypertension",
        "asthma",
        "pneumonia",
        "nephritis",
        "arthritis",
        "ulcer",
        "infection",
        "deficiency",
        "disorder",
        "condition",
        "tetralogy",
        "phenomenon",
        "anomaly",
        "atrophy",
        "dystrophy",
        "sclerosis",
        "cirrhosis",
        "hepatitis",
        "nephropathy",
        "retinopathy",
        "neuropathy",
        "cardiomyopathy",
        "angina",
        "infarction",
        "stroke",
        "lactate",
        "saline",
        "solution",
    }
)

NON_NAME_WORDS = frozenset(
    {
        "patient",
        "pt",
        "doctor",
        "dr",
        "attendant",
        "relative",
        "admitted",
        "discharged",
        "stable",
        "condition",
        "referred",
        "reviewed",
        "advised",
        "continue",
        "tablet",
        "tab",
        "cap",
        "inj",
        "syp",
        "inh",
        "ward",
        "bed",
        "opd",
        "ipd",
        "icu",
        "nicu",
        "picu",
        "ccu",
        "medicine",
        "surgery",
        "pediatrics",
        "paediatrics",
        "obstetrics",
        "gynecology",
        "gynaecology",
        "orthopedics",
        "cardiology",
        "neurology",
        "pulmonary",
        "diagnosis",
        "complaints",
        "history",
        "vitals",
        "advice",
        "review",
        "procedure",
        "medications",
        "course",
        "hospital",
        "charitable",
        "multispeciality",
        "district",
        "clinic",
        "pathology",
        "laboratory",
        "male",
        "female",
        "yrs",
        "years",
        "year",
        "age",
        "umar",
        "umra",
        "aayu",
        "ayu",
        "sex",
        "ling",
        "came",
        "went",
        "brought",
        "accompanied",
        "discharged",
        "treated",
        "conservatively",
        "unknown",
        "none",
        "nil",
        "na",
        "मरीज़",
        "मरीज",
        "रोगी",
        "डॉक्टर",
        "आयु",
        "उम्र",
        "वर्ष",
        "महिला",
        "पुरुष",
        "अस्पताल",
        "दवा",
        "गोली",
        "इंजेक्शन",
        "जांच",
        "रिपोर्ट",
        "भर्ती",
        "छुट्टी",
        "निदान",
        "को",
        "का",
        "की",
        "के",
        "से",
        "में",
        "पर",
        "और",
        "था",
        "थी",
        "थे",
        "है",
        "हैं",
        "ने",
        "यह",
        "वह",
        "उनको",
        "इनको",
    }
) | COMPLAINT_WORDS | CLINICAL_HEAD_NOUNS | NAME_LABEL_STOP_WORDS

# R10 linkage tiers (normalised strong-ID type names from wards.linkage.normalise_strong_id).
# Lifelong person IDs (UIDAI Aadhaar, NHA ABHA number, Income Tax PAN): one value per person,
# so two different values in one cluster are a conflict. Every other strong-ID type is a link
# edge only and never a conflict.
LINK_LIFELONG_ID_TYPES = frozenset({"aadhaar", "abha", "pan"})
# Primary facility-level patient identifier kind paired with LINK_LIFELONG_ID_TYPES as D9 anchor keys.
PRIMARY_ID_TYPE = "MRN"
LINK_ANCHOR_ID_KINDS = frozenset({t.upper() for t in LINK_LIFELONG_ID_TYPES}) | {PRIMARY_ID_TYPE}
# Contact handles can be shared inside a family; on a conflict they are dropped before
# per-issuer IDs (hospital MRN/UHID/IPD, insurance policy numbers).
LINK_CONTACT_ID_TYPES = frozenset({"phone", "email", "abha_address"})
# Per-issuer IDs are matched on their digit core; fewer digits than this is not an ID.
LINK_MIN_ID_DIGITS = 4
# Digit counts of lifelong IDs: Aadhaar 12 (UIDAI), ABHA number 14 (NHA ABDM).
AADHAAR_DIGITS = 12
ABHA_DIGITS = 14

# R13 PIN generalisation: India Post PIN codes have 6 digits; dropped digits become this mark.
PIN_DIGITS = 6
PIN_MASK_CHAR = "*"
# Valid ages in years: below MIN_VALID_AGE or above MAX_VALID_AGE (oldest verified human
# lifespan is 122) a value is not a real age, so it is replaced by the age placeholder, never banded.
MIN_VALID_AGE = 0
MAX_VALID_AGE = 125

# R13 field-meaning words in English, Hindi (Devanagari) and Hinglish. Sources: English and
# Hindi vocabulary; Indian address hierarchy (Census of India: district > tehsil); India Post.
AGE_LABEL_WORDS = ("age", "umar", "आयु", "उम्र")
AGE_UNIT_WORDS = ("y", "yr", "yrs", "year", "years", "वर्ष", "साल")
SEX_LABEL_WORDS = ("sex", "gender", "ling", "लिंग")
SEX_VALUE_WORDS = ("m", "f", "male", "female", "पुरुष", "महिला", "स्त्री")
DISTRICT_MARKER_WORDS = ("distt.", "distt", "district", "जिला")
TEHSIL_MARKER_WORDS = ("tehsil", "तहसील")
# Upper length bound on single-cell/leaf address value-shape classification so clinical paragraphs never trigger it.
ADDRESS_VALUE_MAX_LEN = 180
# policy.yaml location_level value that keeps the tehsil (sub-district) as well as the district.
LOCATION_LEVEL_TEHSIL = "tehsil"
# Location parts below the kept level (house, locality, landmark, village): always removed, and a
# record that loses one counts as generalised (R13).
LOCATION_DETAIL_KINDS = frozenset({"VILLAGE", "HOUSE", "LOCALITY", "LANDMARK"})
PIN_LABEL_WORDS = ("pin", "pincode", "pin code", "postal code", "पिन")

# R12 date parsing. Years outside [DATE_MIN_YEAR, DATE_MAX_YEAR] are not read as dates.
DATE_MIN_YEAR = 1900
DATE_MAX_YEAR = 2099
# Two-digit years >= this pivot are 19xx, else 20xx: DOBs back to 1930, visits up to 2029.
TWO_DIGIT_YEAR_PIVOT = 30
# A date written without a year takes the year of the first full date in the same text;
# with none, this leap year, so every day-month pair (incl. 29 Feb) parses.
YEARLESS_REFERENCE_YEAR = 2000
# English month abbreviations missing from calendar.month_abbr (Oxford style "Sept").
MONTH_ABBR_VARIANTS = {"sept": 9}

REQUIRED_POLICY_KEYS = (
    "age_band_years",
    "age_top_code",
    "date_shift_max_days",
    "date_shift_min_abs_days",
    "location_level",
    "pin_prefix_digits",
    "min_group_size",
    "rare_condition_max_profiles",
    "rare_action",
)

_INT_POLICY_KEYS = frozenset(
    {
        "age_band_years",
        "age_top_code",
        "date_shift_max_days",
        "date_shift_min_abs_days",
        "pin_prefix_digits",
        "min_group_size",
        "rare_condition_max_profiles",
    }
)


class PolicyError(ValueError):
    """Raised when policy.yaml is missing, malformed, or out of valid range."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Policy:
    """Privacy policy settings loaded from config/policy.yaml."""

    age_band_years: int
    age_top_code: int
    date_shift_max_days: int
    date_shift_min_abs_days: int
    location_level: str
    pin_prefix_digits: int
    min_group_size: int
    rare_condition_max_profiles: int
    rare_action: str


def validate_policy(policy: Policy) -> Policy:
    """Validate policy field ranges. Raises PolicyError on invalid values."""
    if policy.age_band_years < 1:
        raise PolicyError("invalid_policy_range")
    if policy.age_top_code < policy.age_band_years:
        raise PolicyError("invalid_policy_range")
    if policy.date_shift_max_days < 1:
        raise PolicyError("invalid_policy_range")
    if policy.date_shift_min_abs_days < 1 or policy.date_shift_min_abs_days > policy.date_shift_max_days:
        raise PolicyError("invalid_policy_range")
    if policy.location_level not in ("district", "tehsil", "state"):
        raise PolicyError("invalid_policy_range")
    if policy.pin_prefix_digits < 1 or policy.pin_prefix_digits > 6:
        raise PolicyError("invalid_policy_range")
    if policy.min_group_size < 1:
        raise PolicyError("invalid_policy_range")
    if policy.rare_condition_max_profiles < 1:
        raise PolicyError("invalid_policy_range")
    if policy.rare_action not in ("coarsen", "suppress"):
        raise PolicyError("invalid_policy_range")
    return policy


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> Policy:
    """Parse and validate `key: value` lines from policy.yaml.

    Fails closed with PolicyError if the file is missing, invalid, or incomplete.
    Complexity: O(bytes) in the policy file size.
    """
    if not path.is_file():
        raise PolicyError("missing_policy_file")

    raw_values: dict[str, object] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        clean_line = line.split("#", 1)[0].strip()
        if not clean_line:
            continue
        if ":" not in clean_line:
            raise PolicyError("invalid_policy_syntax")
        key, val = (part.strip() for part in clean_line.split(":", 1))
        if not key or not val:
            raise PolicyError("invalid_policy_syntax")
        if key in _INT_POLICY_KEYS:
            if not val.lstrip("-").isdigit():
                raise PolicyError("invalid_policy_value")
            raw_values[key] = int(val)
        else:
            raw_values[key] = val

    for req_key in REQUIRED_POLICY_KEYS:
        if req_key not in raw_values:
            raise PolicyError("missing_policy_key")

    policy = Policy(
        age_band_years=int(raw_values["age_band_years"]),  # type: ignore[arg-type]
        age_top_code=int(raw_values["age_top_code"]),  # type: ignore[arg-type]
        date_shift_max_days=int(raw_values["date_shift_max_days"]),  # type: ignore[arg-type]
        date_shift_min_abs_days=int(raw_values["date_shift_min_abs_days"]),  # type: ignore[arg-type]
        location_level=str(raw_values["location_level"]),
        pin_prefix_digits=int(raw_values["pin_prefix_digits"]),  # type: ignore[arg-type]
        min_group_size=int(raw_values["min_group_size"]),  # type: ignore[arg-type]
        rare_condition_max_profiles=int(raw_values["rare_condition_max_profiles"]),  # type: ignore[arg-type]
        rare_action=str(raw_values["rare_action"]),
    )
    return validate_policy(policy)


def require_secret(env_var: str = "RAKSHA_SECRET") -> bytes:
    """Read the release secret from the environment; fail closed if missing or empty."""
    secret = os.environ.get(env_var, "")
    if not secret:
        raise RuntimeError(f"missing required environment variable: {env_var}")
    return secret.encode("utf-8")
