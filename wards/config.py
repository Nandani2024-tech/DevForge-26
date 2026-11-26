"""Configuration, policy loading and validation, and environment secret access."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPORT_SCHEMA = "raksha-report/1"
SUPPORTED_EXTENSIONS = (".csv", ".tsv", ".json", ".txt")
RSS_SAMPLE_INTERVAL_SEC = 0.05
DEFAULT_POLICY_PATH = Path(__file__).resolve().parent.parent / "config" / "policy.yaml"

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
