"""N4 slice 1 tests: R9 base64 channel, R4 FHIR R4B validity, R8 preservation, and linear scaling."""
from __future__ import annotations

import base64
import json
import textwrap
import time
from pathlib import Path

from wards.channels import (
    Base64Format,
    decode_base64_payload,
    decode_printable_utf8,
    encode_base64_payload,
)
from wards.config import (
    BASE64_BINARY_REASON,
    BASE64_DEPTH_REASON,
    BASE64_INVALID_REASON,
    BASE64_MAX_DEPTH,
    BASE64_MIME_LINE_WIDTH,
    BASE64_PLACEHOLDER,
    load_policy,
)
from wards.pipeline import run_pipeline

_TEST_SECRET = b"unit-test-base64-secret"


def _b64_std(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _b64_url(text: str, *, unpadded: bool = False) -> str:
    out = base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")
    return out.rstrip("=") if unpadded else out


def _wrap_mime(b64_str: str, width: int = BASE64_MIME_LINE_WIDTH, sep: str = "\r\n", trailing: str = "") -> str:
    return sep.join(textwrap.wrap(b64_str, width=width, break_long_words=True, break_on_hyphens=False)) + trailing


def test_hand_derived_hi_oracle_and_unchanged_preserved(tmp_path: Path) -> None:
    assert _b64_std("Hi") == "SGk="
    decoded = decode_base64_payload("SGk=", min_len=2, strict_whitespace=False)
    assert decoded is not None
    assert decoded.raw_bytes == b"Hi"
    assert decode_printable_utf8(decoded.raw_bytes) == "Hi"
    assert encode_base64_payload(b"Hi", decoded.fmt) == "SGk="

    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    clean_note = {
        "document": "note",
        "attachment": {"contentType": "text/plain", "data": "SGk="},
        "short_leaf": "SGk=",
    }
    (inp / "doc.json").write_text(json.dumps(clean_note), encoding="utf-8")

    res = run_pipeline(inp, out, _TEST_SECRET, load_policy())
    san = json.loads((out / "sanitized" / "doc.json").read_text(encoding="utf-8"))
    assert san["attachment"]["data"] == "SGk="
    assert san["attachment"]["contentType"] == "text/plain"
    assert san["short_leaf"] == "SGk="
    assert res.report["counts"]["files_sanitized"] == 1


def test_clinical_values_preserved_inside_base64_payloads(tmp_path: Path) -> None:
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    clinical_text = "Diagnosis: Hypothyroidism, BP 120/80 mmHg, Paracetamol 500 mg 1-0-1, SpO2 98%"
    encoded = _b64_std(clinical_text)
    payload = {
        "summary_blob": encoded,
        "bare_terms": ["Hypothyroidism", "Consultation", "Paracetamol", "Azithromycin"],
        "attachment": {"contentType": "text/plain", "data": _b64_std("Name: Eeshani Banerjee; 500 mg Paracetamol BD")},
    }
    (inp / "clinical.json").write_text(json.dumps(payload), encoding="utf-8")

    run_pipeline(inp, out, _TEST_SECRET, load_policy())
    san = json.loads((out / "sanitized" / "clinical.json").read_text(encoding="utf-8"))
    assert san["summary_blob"] == encoded
    assert san["bare_terms"] == ["Hypothyroidism", "Consultation", "Paracetamol", "Azithromycin"]
    att_decoded = base64.b64decode(san["attachment"]["data"]).decode("utf-8")
    assert "Eeshani" not in att_decoded and "Banerjee" not in att_decoded
    assert "[PATIENT_NAME]" in att_decoded
    assert "500 mg Paracetamol BD" in att_decoded


def test_plain_json_variants_data_uri_and_linkage(tmp_path: Path) -> None:
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()

    # Cross-file linkage via identity inside base64 payload + Devanagari/urlsafe/MIME-wrap/data-URI
    note_plain = "Name: Zoravar Chatterjee, UHID: HOSP-884422, Phone: 9000012345, DOB: 14-03-1988, visit 10/01/2026"
    hindi_note = "नाम: ज़ोरावर चटर्जी, मोबाइल: 9000012345"
    wrapped = _wrap_mime(
        _b64_std("Patient Name: Zoravar Chatterjee " + ("clinical ok; " * 8)),
        width=76,
        sep="\r\n",
        trailing="\r\n",
    )
    urlsafe_unpadded = _b64_url("Patient Name: Devika Menon, >note+ref~ok", unpadded=True)
    assert "-" in urlsafe_unpadded or "_" in urlsafe_unpadded or "=" not in urlsafe_unpadded

    form = {
        "patient_ref": "pending",
        "meta_tag": "intake",
        "empty_leaf": "",
        "blob_wrapped": wrapped,
        "blob_urlsafe": urlsafe_unpadded,
        "uri_text": "data:text/plain;charset=utf-8;base64," + _b64_std(note_plain),
        "uri_hindi": "data:text/plain;base64," + _b64_std(hindi_note),
        "uri_json": "data:application/json;base64,"
        + _b64_std(json.dumps({"patient_name": "Zoravar Chatterjee", "diagnosis": "Viral Fever"})),
    }
    csv_text = "uhid,name,notes\nHOSP-884422,Zoravar Chatterjee,Follow up 20/01/2026\n"
    (inp / "intake.json").write_text(json.dumps(form), encoding="utf-8")
    (inp / "visits.csv").write_text(csv_text, encoding="utf-8")

    res = run_pipeline(inp, out, _TEST_SECRET, load_policy())
    san = json.loads((out / "sanitized" / "intake.json").read_text(encoding="utf-8"))

    # 1. Both files link to the same PSN because Pass 1 harvested UHID + name from base64
    psns = {r["patient"] for r in res.records}
    assert len(psns) == 1 and None not in psns

    # 2. Empty leaf preserved
    assert san["empty_leaf"] == ""

    # 3. MIME 76-col wrapping and CRLF trailing newline preserved
    san_wrapped = san["blob_wrapped"]
    assert "\r\n" in san_wrapped and san_wrapped.endswith("\r\n")
    lines = san_wrapped[:-2].split("\r\n")
    assert all(len(line) == 76 for line in lines[:-1])
    decoded_wrapped = base64.b64decode(san_wrapped).decode("utf-8")
    assert "Zoravar" not in decoded_wrapped and "[PATIENT_NAME]" in decoded_wrapped

    # 4. Unpadded urlsafe variant preserved without padding or '+'/'/'
    san_url = san["blob_urlsafe"]
    assert "=" not in san_url and "+" not in san_url and "/" not in san_url
    rem = len(san_url) % 4
    padded_url = san_url + ("=" * ((4 - rem) % 4))
    decoded_url = base64.urlsafe_b64decode(padded_url).decode("utf-8")
    assert "Devika" not in decoded_url and "[PATIENT_NAME]" in decoded_url

    # 5. data: URI prefixes kept intact; decoded contents scrubbed
    assert san["uri_text"].startswith("data:text/plain;charset=utf-8;base64,")
    txt_body = base64.b64decode(san["uri_text"].split(",", 1)[1]).decode("utf-8")
    for tok in ("Zoravar", "Chatterjee", "884422", "9000012345"):
        assert tok not in txt_body

    assert san["uri_hindi"].startswith("data:text/plain;base64,")
    hi_body = base64.b64decode(san["uri_hindi"].split(",", 1)[1]).decode("utf-8")
    assert "ज़ोरावर" not in hi_body and "9000012345" not in hi_body

    assert san["uri_json"].startswith("data:application/json;base64,")
    json_body = json.loads(base64.b64decode(san["uri_json"].split(",", 1)[1]).decode("utf-8"))
    assert json_body["patient_name"] == "[PATIENT_NAME]"
    assert json_body["diagnosis"] == "Viral Fever"


def test_nested_base64_and_depth_cap_fail_closed(tmp_path: Path) -> None:
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()

    # Depth 3 (valid): root -> lvl1 -> lvl2 -> lvl3 text (cleaned!)
    # Depth 4 (> BASE64_MAX_DEPTH=3): root -> lvl1 -> lvl2 -> lvl3 -> lvl4 (redacted with depth reason!)
    lvl4 = _b64_std("Patient Name: Hidden Too Deep")
    lvl3_over = _b64_std(json.dumps({"too_deep": lvl4, "keep_dx": "Asthma"}))
    lvl2_over = _b64_std(json.dumps({"inner3": lvl3_over}))
    lvl1_over = _b64_std(json.dumps({"inner2": lvl2_over}))

    lvl3_ok = _b64_std("Patient Name: Niharika Roy, 500 mg ok")
    lvl2_ok = _b64_std(json.dumps({"inner3": lvl3_ok}))
    lvl1_ok = _b64_std(json.dumps({"inner2": lvl2_ok}))

    (inp / "nested.json").write_text(json.dumps({"ok_chain": lvl1_ok, "deep_chain": lvl1_over}), encoding="utf-8")

    res = run_pipeline(inp, out, _TEST_SECRET, load_policy())
    san = json.loads((out / "sanitized" / "nested.json").read_text(encoding="utf-8"))

    # Level 3 text was decoded and cleaned while preserving clinical drug dose
    d1 = json.loads(base64.b64decode(san["ok_chain"]).decode("utf-8"))
    d2 = json.loads(base64.b64decode(d1["inner2"]).decode("utf-8"))
    d3 = base64.b64decode(d2["inner3"]).decode("utf-8")
    assert "Niharika" not in d3 and "[PATIENT_NAME]" in d3 and "500 mg ok" in d3

    # Level 4 exceeded depth cap -> replaced with BASE64_PLACEHOLDER, not decoded or kept raw
    o1 = json.loads(base64.b64decode(san["deep_chain"]).decode("utf-8"))
    o2 = json.loads(base64.b64decode(o1["inner2"]).decode("utf-8"))
    o3 = json.loads(base64.b64decode(o2["inner3"]).decode("utf-8"))
    assert o3["keep_dx"] == "Asthma"
    assert base64.b64decode(o3["too_deep"]).decode("utf-8") == BASE64_PLACEHOLDER
    assert res.report["reason_counts"].get(BASE64_DEPTH_REASON, 0) >= 1
    assert BASE64_MAX_DEPTH == 3


def test_binary_and_malformed_attachments_fail_closed(tmp_path: Path) -> None:
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()

    png_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRfakePNGbytes").decode("ascii")
    jpg_b64 = base64.b64encode(b"\xff\xd8\xff\xe0\x00\x10JFIFfakeJPEGbytes").decode("ascii")
    pdf_b64 = base64.b64encode(b"%PDF-1.4\nfake PDF stream with raw text").decode("ascii")

    doc = {
        "png_att": {"contentType": "image/png", "data": png_b64},
        "jpg_uri": "data:image/jpeg;base64," + jpg_b64,
        "pdf_raw_leaf": pdf_b64,
        "truncated_att": {"contentType": "text/plain", "data": "abcde"},
        "wrong_pad_att": {"contentType": "text/plain", "data": "SGk=="},
        "bad_chars_att": {"contentType": "text/plain", "data": "not!valid@base64#"},
    }
    (inp / "binary_bad.json").write_text(json.dumps(doc), encoding="utf-8")

    res = run_pipeline(inp, out, _TEST_SECRET, load_policy())
    san = json.loads((out / "sanitized" / "binary_bad.json").read_text(encoding="utf-8"))

    expected_b64 = base64.b64encode(BASE64_PLACEHOLDER.encode("utf-8")).decode("ascii")
    assert san["png_att"]["contentType"] == "image/png"
    assert san["png_att"]["data"] == expected_b64
    assert san["jpg_uri"] == "data:image/jpeg;base64," + expected_b64
    assert san["pdf_raw_leaf"] == expected_b64
    assert san["truncated_att"]["data"] == expected_b64
    assert san["wrong_pad_att"]["data"] == expected_b64
    assert san["bad_chars_att"]["data"] == expected_b64

    assert res.report["reason_counts"].get(BASE64_BINARY_REASON, 0) == 3
    assert res.report["reason_counts"].get(BASE64_INVALID_REASON, 0) == 3


def test_fhir_bundle_r4b_valid_and_refs_resolve(tmp_path: Path, kit_dir: Path) -> None:
    # fhir.resources is a required test dependency (Reuse Stack); a missing package fails the test.
    from fhir.resources.R4B.bundle import Bundle as FhirR4BBundle  # type: ignore[import-not-found]

    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()

    pat_url = "urn:uuid:11111111-1111-4111-8111-111111111111"
    dr_url = "urn:uuid:22222222-2222-4222-8222-222222222222"
    doc_url = "urn:uuid:33333333-3333-4333-8333-333333333333"
    media_url = "urn:uuid:44444444-4444-4444-8444-444444444444"

    bundle = {
        "resourceType": "Bundle",
        "id": "b-base64-test",
        "type": "collection",
        "entry": [
            {
                "fullUrl": pat_url,
                "resource": {
                    "resourceType": "Patient",
                    "id": "pat-1",
                    "identifier": [{"system": "urn:oid:1.2.3.4", "value": "MRN-775533"}],
                    "name": [{"text": "Zoravar Chatterjee", "family": "Chatterjee", "given": ["Zoravar"]}],
                    "birthDate": "1985-06-15",
                },
            },
            {
                "fullUrl": dr_url,
                "resource": {
                    "resourceType": "Practitioner",
                    "id": "prac-1",
                    "name": [{"text": "Dr. Sanjay Kulkarni"}],
                },
            },
            {
                "fullUrl": doc_url,
                "resource": {
                    "resourceType": "DocumentReference",
                    "id": "doc-1",
                    "status": "current",
                    "subject": {"reference": pat_url},
                    "author": [{"reference": dr_url}],
                    "content": [
                        {
                            "attachment": {
                                "contentType": "text/plain",
                                "data": _b64_std(
                                    "Referral: Zoravar Chatterjee (MRN-775533), mobile 9000011111, referred for Hypothyroidism."
                                ),
                                "title": "Referral note",
                            }
                        },
                        {
                            "attachment": {
                                "contentType": "application/pdf",
                                "data": base64.b64encode(b"%PDF-1.5\nscanned binary doc").decode("ascii"),
                                "title": "Consent scan",
                            }
                        },
                    ],
                },
            },
            {
                "fullUrl": media_url,
                "resource": {
                    "resourceType": "Media",
                    "id": "med-1",
                    "status": "completed",
                    "subject": {"reference": pat_url},
                    "content": {
                        "contentType": "text/plain",
                        "data": _b64_std("Patient Name: Zoravar Chatterjee, phone 9000011111, SpO2 99%"),
                    },
                },
            },
        ],
    }
    (inp / "fhir_att.json").write_text(json.dumps(bundle), encoding="utf-8")

    run_pipeline(inp, out, _TEST_SECRET, load_policy())
    san_text = (out / "sanitized" / "fhir_att.json").read_text(encoding="utf-8")
    san = json.loads(san_text)

    parsed_bundle = FhirR4BBundle.model_validate_json(san_text)
    assert parsed_bundle.get_resource_type() == "Bundle"

    def _assert_refs_and_attachments(doc: dict[str, object]) -> None:
        assert doc.get("resourceType") == "Bundle"
        entries = doc.get("entry")
        assert isinstance(entries, list)
        full_urls = {entry["fullUrl"] for entry in entries if isinstance(entry, dict) and "fullUrl" in entry}
        refs: list[str] = []

        def _walk(node: object) -> None:
            if isinstance(node, dict):
                ref = node.get("reference")
                if isinstance(ref, str):
                    refs.append(ref)
                if "data" in node and isinstance(node["data"], str) and (
                    "contentType" in node or "attachment" in str(doc)
                ):
                    raw_b = base64.b64decode(node["data"], validate=True)
                    assert raw_b is not None
                for v in node.values():
                    _walk(v)
            elif isinstance(node, list):
                for item in node:
                    _walk(item)

        _walk(doc)
        assert refs and all(ref in full_urls for ref in refs)

    _assert_refs_and_attachments(san)

    # Structural fields preserved; attachments cleaned and valid base64
    doc_res = san["entry"][2]["resource"]
    med_res = san["entry"][3]["resource"]
    assert doc_res["resourceType"] == "DocumentReference" and doc_res["id"] == "doc-1"
    assert doc_res["content"][0]["attachment"]["contentType"] == "text/plain"
    text_att = base64.b64decode(doc_res["content"][0]["attachment"]["data"]).decode("utf-8")
    for leaked in ("Zoravar", "Chatterjee", "775533", "9000011111"):
        assert leaked not in text_att
    assert "Hypothyroidism" in text_att

    assert doc_res["content"][1]["attachment"]["contentType"] == "application/pdf"
    assert base64.b64decode(doc_res["content"][1]["attachment"]["data"]).decode("utf-8") == BASE64_PLACEHOLDER

    med_att = base64.b64decode(med_res["content"]["data"]).decode("utf-8")
    assert "Zoravar" not in med_att and "9000011111" not in med_att and "SpO2 99%" in med_att

    # Also verify every FHIR bundle under dev/input/fhir/ resolves all references cleanly and keeps valid base64
    dev_fhir = kit_dir / "dev" / "input" / "fhir"
    assert dev_fhir.is_dir(), "kit dev/input/fhir fixture missing"
    fhir_out = tmp_path / "dev_fhir_out"
    run_pipeline(dev_fhir, fhir_out, _TEST_SECRET, load_policy())
    sanitized_bundles = sorted((fhir_out / "sanitized").glob("*.json"))
    assert sanitized_bundles, "no sanitized FHIR bundles produced"
    for p in sanitized_bundles:
        b_text = p.read_text(encoding="utf-8")
        b_obj = json.loads(b_text)
        FhirR4BBundle.model_validate_json(b_text)
        _assert_refs_and_attachments(b_obj)


def test_huge_base64_scales_linearly(tmp_path: Path) -> None:
    policy = load_policy()
    chunk = "Patient Name: Zoravar Chatterjee, Paracetamol 500 mg BD, SpO2 98%.\n"
    timings: list[float] = []
    for factor in (1, 3, 9):
        inp = tmp_path / f"in_{factor}"
        out = tmp_path / f"out_{factor}"
        inp.mkdir()
        text_payload = chunk * (250 * factor)
        (inp / "huge.json").write_text(
            json.dumps({"attachment": {"contentType": "text/plain", "data": _b64_std(text_payload)}}),
            encoding="utf-8",
        )
        t0 = time.perf_counter()
        run_pipeline(inp, out, _TEST_SECRET, policy)
        timings.append(time.perf_counter() - t0)

    # 9x payload size must finish within linear budget relative to 3x/1x (not quadratic)
    ratio_9_vs_3 = timings[2] / max(timings[1], 1e-4)
    assert ratio_9_vs_3 < 6.0, f"Super-linear base64 scaling: {timings}"


def test_r6_r9_bare_id_that_decodes_as_base64_is_still_redacted(tmp_path: Path) -> None:
    # "345235503650" is an invented 12-digit Aadhaar-shaped value (absent from dev/input). Its
    # characters also form valid base64 that decodes to printable UTF-8, so the plain-JSON base64
    # heuristic must never stop the identifier detectors from running on it. "123456789012" is
    # the control: same shape, does not decode as printable UTF-8.
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    doc = {"note": "345235503650", "note_control": "123456789012"}
    (inp / "ids.json").write_text(json.dumps(doc), encoding="utf-8")
    run_pipeline(inp, out, _TEST_SECRET, load_policy())
    san = json.loads((out / "sanitized" / "ids.json").read_text(encoding="utf-8"))
    assert san["note_control"] != "123456789012"
    assert san["note"] != "345235503650"
    assert "345235503650" not in json.dumps(san)


def test_r7_r9_decoded_base64_catches_label_free_runtime_evidence_name(tmp_path: Path) -> None:
    # Invented label-free name (absent from dev/input) appearing without any label in decoded
    # base64 payloads must be caught via Pass 1 run-time name evidence while preserving doctors
    # and clinical terms.
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()

    (inp / "roster.csv").write_text(
        "uhid,patient_name,note\nHOSP-992211,Mrinalini Goswami,OPD review\n",
        encoding="utf-8",
    )
    decoded_att = "Memo: Mrinalini Goswami reviewed by Dr. Bhargav Kulkarni; Paracetamol 500 mg BD."
    decoded_leaf = "Follow-up summary of Mrinalini Goswami with Hb 13.4 g/dL and normal BP."
    doc = {
        "patient_ref": "HOSP-992211",
        "attachment": {"contentType": "text/plain", "data": _b64_std(decoded_att)},
        "summary_blob": _b64_std(decoded_leaf),
    }
    (inp / "memo.json").write_text(json.dumps(doc), encoding="utf-8")

    run_pipeline(inp, out, _TEST_SECRET, load_policy())
    san = json.loads((out / "sanitized" / "memo.json").read_text(encoding="utf-8"))

    att_out = base64.b64decode(san["attachment"]["data"]).decode("utf-8")
    assert "Mrinalini" not in att_out and "Goswami" not in att_out
    assert "[PATIENT_NAME]" in att_out
    assert "Dr. Bhargav Kulkarni" in att_out
    assert "Paracetamol 500 mg BD" in att_out

    leaf_out = base64.b64decode(san["summary_blob"]).decode("utf-8")
    assert "Mrinalini" not in leaf_out and "Goswami" not in leaf_out
    assert "[PATIENT_NAME]" in leaf_out
    assert "Hb 13.4 g/dL" in leaf_out


def test_r4_r8_fhir_sampled_data_stays_unchanged(tmp_path: Path) -> None:
    # FHIR Observation.valueSampledData.data holds decimal space-separated telemetry, never
    # base64; structural Attachment detection must leave SampledData.data untouched.
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()

    pat_url = "urn:uuid:aaaa1111-1111-4111-8111-111111111111"
    obs_url = "urn:uuid:bbbb2222-2222-4222-8222-222222222222"
    bundle = {
        "resourceType": "Bundle",
        "id": "b-sampled-data",
        "type": "collection",
        "entry": [
            {
                "fullUrl": pat_url,
                "resource": {
                    "resourceType": "Patient",
                    "id": "pat-sd",
                    "identifier": [{"system": "urn:oid:1.2.3.4", "value": "MRN-331199"}],
                    "name": [{"text": "Mrinalini Goswami"}],
                },
            },
            {
                "fullUrl": obs_url,
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-sd",
                    "status": "final",
                    "subject": {"reference": pat_url},
                    "valueSampledData": {
                        "origin": {"value": 0},
                        "period": 100,
                        "dimensions": 1,
                        "data": "1.2 3.4 E",
                    },
                    "component": [
                        {
                            "code": {"text": "Waveform"},
                            "valueSampledData": {
                                "origin": {"value": 0},
                                "period": 50,
                                "dimensions": 1,
                                "data": "1.2 3.4 5.6 7.8 E 9.1",
                            },
                        }
                    ],
                },
            },
        ],
    }
    (inp / "sampled.json").write_text(json.dumps(bundle), encoding="utf-8")

    run_pipeline(inp, out, _TEST_SECRET, load_policy())
    san = json.loads((out / "sanitized" / "sampled.json").read_text(encoding="utf-8"))
    obs_res = san["entry"][1]["resource"]
    assert obs_res["valueSampledData"]["data"] == "1.2 3.4 E"
    assert obs_res["component"][0]["valueSampledData"]["data"] == "1.2 3.4 5.6 7.8 E 9.1"
