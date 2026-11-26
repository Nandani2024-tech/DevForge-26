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
