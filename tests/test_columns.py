"""Tests for R5 structured column & JSON key classification and shape voting."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from wards.channels import ChannelEvidence
from wards.columns import classify_csv_columns, classify_header_tokens, classify_json_key
from wards.config import PLACEHOLDERS, load_policy
from wards.pipeline import run_pipeline


def test_meaning_vocabulary_synonyms() -> None:
    assert classify_header_tokens("Patient's Name") == "PATIENT_NAME"
    assert classify_header_tokens("Contact#") == "PHONE"
    assert classify_header_tokens("Gram/Mohalla") == "VILLAGE"
    assert classify_header_tokens("Birth Dt") == "DOB"
    assert classify_header_tokens("Postal Code") == "PIN"
    assert classify_header_tokens("Ref Doctor") == "PRESERVE_EXACT"
    assert classify_header_tokens("District") == "PRESERVE_EXACT"


def test_numeric_empty_headers_and_mixed_blanks_via_shape_vote() -> None:
    header = ["", "123", "456", "789", "Notes"]
    rows = [
        ["4123 4567 8901", "", "person.a@example.org", "226001", "Dolo 650mg 1-1-1 x 5 days"],
        ["", "9876543210", "", "226002", "BP 117/82"],
        ["3972 0583 9628", "", "person.b@example.org", "", "plt 1,45,000"],
    ]
    kinds = classify_csv_columns(header, rows, ChannelEvidence())
    assert kinds[0] == "AADHAAR"
    assert kinds[1] == "PHONE"
    assert kinds[2] == "EMAIL"
    assert kinds[3] == "PIN"
    assert kinds[4] == "FREE_TEXT"


def test_json_context_preserves_clinical_names_and_int_types(tmp_path: Path) -> None:
    assert classify_json_key("facility", "name") == "PRESERVE_EXACT"
    assert classify_json_key("panels", "name") == "PRESERVE_EXACT"
    assert classify_json_key("patient", "name") == "PATIENT_NAME"
    assert classify_json_key("guardian", "name") == "RELATIVE"

    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    doc = {
        "facility": {"name": "Rural Health Centre"},
        "patient": {
            "uhid": "CLI-90001",
            "name": "Meera Sen",
            "dob": "1985-04-12",
            "aadhar_no": 412345678901,
            "district": "Lucknow",
        },
        "panels": [{"name": "Complete Blood Count", "result": "13.2"}],
    }
    (inp / "report.json").write_text(json.dumps(doc), encoding="utf-8")

    run_pipeline(inp=inp, out=out, secret=b"col-secret", policy=load_policy())
    san = json.loads((out / "sanitized" / "report.json").read_text(encoding="utf-8"))

    assert san["facility"]["name"] == "Rural Health Centre"
    assert san["panels"][0]["name"] == "Complete Blood Count"
    assert san["patient"]["uhid"].startswith("PSN-")
    assert san["patient"]["name"] == PLACEHOLDERS["PATIENT_NAME"]
    # R12: DOB shifted deterministically preserving ISO format
    assert san["patient"]["dob"] != "1985-04-12"
    assert len(san["patient"]["dob"]) == 10 and san["patient"]["dob"][4] == "-" and san["patient"]["dob"][7] == "-"
    assert san["patient"]["district"] == "Lucknow"
    assert isinstance(san["patient"]["aadhar_no"], int)
    assert san["patient"]["aadhar_no"] == 0


def test_r5_fhir_reference_display_to_patient_is_redacted(tmp_path: Path) -> None:
    # Hand-derived: Reference.display that points at a Patient entry carries the patient's
    # name (structured slot), whatever resource holds the reference. A display pointing at a
    # Practitioner is a doctor name and is kept (R8).
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    pat_url = "urn:uuid:00000000-0000-4000-8000-000000000001"
    doc_url = "urn:uuid:00000000-0000-4000-8000-000000000002"
    bundle = {
        "resourceType": "Bundle",
        "type": "document",
        "entry": [
            {"fullUrl": "urn:uuid:00000000-0000-4000-8000-000000000003",
             "resource": {"resourceType": "Composition", "status": "final", "title": "Discharge summary",
                          "subject": {"reference": pat_url, "display": "Tarini Okafor"},
                          "author": [{"reference": doc_url, "display": "Dr. Ilesh Varma"}]}},
            {"fullUrl": pat_url,
             "resource": {"resourceType": "Patient", "name": [{"text": "Tarini Okafor"}]}},
            {"fullUrl": doc_url,
             "resource": {"resourceType": "Practitioner", "name": [{"text": "Dr. Ilesh Varma"}]}},
        ],
    }
    (inp / "bundle.json").write_text(json.dumps(bundle), encoding="utf-8")

    run_pipeline(inp=inp, out=out, secret=b"fhir-secret", policy=load_policy())
    text = (out / "sanitized" / "bundle.json").read_text(encoding="utf-8")
    san = json.loads(text)

    assert "Tarini" not in text and "Okafor" not in text
    comp = san["entry"][0]["resource"]
    assert comp["subject"]["reference"] == pat_url
    assert comp["author"][0]["display"] == "Dr. Ilesh Varma"
    assert comp["title"] == "Discharge summary"


def test_r5_fhir_patient_text_classified_by_parent_element(tmp_path: Path) -> None:
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    bundle = {
        "resourceType": "Bundle",
        "type": "document",
        "entry": [
            {
                "fullUrl": "urn:uuid:00000000-0000-4000-8000-000000000010",
                "resource": {
                    "resourceType": "Patient",
                    "name": [{"text": "Tarini Okafor", "given": ["Tarini"], "family": "Okafor"}],
                    "maritalStatus": {"text": "Married"},
                    "communication": [{"language": {"text": "Hindi"}}],
                    "address": [{"text": "14 Canal Road", "district": "Kanpur"}],
                },
            }
        ],
    }
    (inp / "patient.json").write_text(json.dumps(bundle), encoding="utf-8")

    run_pipeline(inp=inp, out=out, secret=b"fhir-text-secret", policy=load_policy())
    san = json.loads((out / "sanitized" / "patient.json").read_text(encoding="utf-8"))
    pat = san["entry"][0]["resource"]
    assert pat["name"][0]["text"] == PLACEHOLDERS["PATIENT_NAME"]
    assert pat["name"][0]["given"] == [PLACEHOLDERS["PATIENT_NAME"]]
    assert pat["maritalStatus"]["text"] == "Married"
    assert pat["communication"][0]["language"]["text"] == "Hindi"
    assert pat["address"][0]["text"] == PLACEHOLDERS["ADDRESS"]
    assert pat["address"][0]["district"] == "Kanpur"


def test_renamed_csv_columns_end_to_end(tmp_path: Path) -> None:
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    csv_text = (
        "Pt. Ref#,Patient's Name,Guardian Name,Birth Date,Gram/Mohalla,Postal Zip,"
        "Contact#,Consultant,District,Drug\n"
        "HOSP-88101,Kiran Devi,Mohan Lal,14/06/1980,Rampur,226001,"
        "+91-98765-43210,Dr. Verma,Lucknow,Paracetamol 500 mg\n"
    )
    (inp / "renamed.csv").write_text(csv_text, encoding="utf-8")

    run_pipeline(inp=inp, out=out, secret=b"rename-secret", policy=load_policy())
    rows = list(csv.reader(io.StringIO((out / "sanitized" / "renamed.csv").read_text(encoding="utf-8"), newline="")))
    assert rows[0] == [
        "Pt. Ref#",
        "Patient's Name",
        "Guardian Name",
        "Birth Date",
        "Gram/Mohalla",
        "Postal Zip",
        "Contact#",
        "Consultant",
        "District",
        "Drug",
    ]
    data = rows[1]
    assert data[0].startswith("PSN-")
    assert data[1] == PLACEHOLDERS["PATIENT_NAME"]
    assert data[2] == PLACEHOLDERS["RELATIVE"]
    # R12 shifts DOB preserving DD/MM/YYYY format; R13 keeps 3-digit PIN prefix
    assert data[3] != "14/06/1980" and len(data[3]) == 10 and data[3][2] == "/" and data[3][5] == "/"
    assert data[4] == PLACEHOLDERS["VILLAGE"]
    assert data[5] == "226***"
    assert data[6] == PLACEHOLDERS["PHONE"]
    assert data[7] == "Dr. Verma"
    assert data[8] == "Lucknow"
    assert data[9] == "Paracetamol 500 mg"
