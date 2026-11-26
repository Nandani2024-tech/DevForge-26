# 03-prior-art (2026-11-26; registry = PyPI JSON API; smoke in a scratch venv, Windows, Python 3.11)
## Reuse Stack
R-id | need | package or API | version | install command or endpoint | license | smoke
R2,R3,R6,R11,R12,R15,R19 | encodings, csv/json, regex, HMAC, SHA-256, dates, base64, NFKC | Python stdlib (codecs, csv, json, re, hmac, hashlib, datetime, base64, unicodedata) | 3.11 | none | PSF | pass (oracles in 02-domain sec 5 reproduced)
R20 | process-tree peak RSS on Windows + Linux | psutil | 7.2.2 | pip install psutil==7.2.2 | BSD-3-Clause | pass
R18 | AES-GCM for intermediates at rest | cryptography (hazmat AESGCM) | 50.0.2 | pip install cryptography==50.0.2 | Apache-2.0 OR BSD-3-Clause | not run (46.0.5 present locally)
R10 | fuzzy string similarity for names | rapidfuzz | 3.14.5 | pip install rapidfuzz==3.14.5 | MIT | not run (import only)
R10 | phonetic keys (soundex/metaphone/MRA) | jellyfish | 1.2.1 | pip install jellyfish==1.2.1 | MIT | not run (MRA call ran incidentally)
R4 (tests only) | structural FHIR check | fhir.resources (R4B models) | 8.3.0 | pip install fhir.resources==8.3.0 (requirements-dev.txt) | BSD | pass (partial: no value-set check)
R22 (tests only) | synthetic names for mutated-dev tests | Faker (en_IN, hi_IN) | 40.63.0 | pip install Faker==40.63.0 (requirements-dev.txt) | MIT | pass (both locales load; hi_IN gives Devanagari)
test | test framework | pytest | 9.2.0 | pip install pytest==9.2.0 (requirements-dev.txt) | MIT | not run
## Coverage gaps
- R5/R7: context-aware column and free-text name detection in 3 scripts. Presidio-style tools are English-NER-first and the PS says off-the-shelf scores poorly. BUILD: labels, honorifics, relations, plus a gazetteer harvested at run time from the input's own structured columns.
- R7 transliteration: BUILD a ~45-consonant Devanagari->Latin table with schwa deletion. It matched indic-transliteration on quality (11/12 vs 10/12), is 30x faster, and adds no deps.
- R9 hidden channels (filenames, keys, headers, metadata, base64), R16, R17, R21: our own pipeline behaviour, nothing to reuse.
- R10 clustering: BUILD rule-based Fellegi-Sunter-style scoring + union-find with conflict checks. splink needs duckdb + pyarrow, overkill for thousands of records.
- R12: BUILD a format-preserving date parse/shift/write-back. dateparser parses but doesn't round-trip the original format and pulls in 4 deps.
- R13/R14: BUILD a group-by k-anonymity check. pycanon pins numpy, pandas, scipy and reportlab versions.
- R4 validation: BUILD a reference-resolution + value-set check (fhir.resources doesn't enforce Bundle.type codes). R24/R25 docs: write them.
## Candidates
- psutil | https://github.com/giampaolo/psutil | RSS of the process and its children | R20 | BSD-3 | 2026-01-28 | 1 | USE | no deps, wheels for both OSes, smoke pass
- cryptography | https://cryptography.io | AESGCM, key gen | R18 | Apache/BSD | 2026-09-30 | 1 | USE | PS-recommended, verified API (02-domain)
- rapidfuzz | https://github.com/rapidfuzz/RapidFuzz | Levenshtein/Jaro-Winkler | R10 | MIT | 3.14.5: 2026-04-07 | 1 | USE | fast C++, no deps; pinned 3.14.5 (3.14.6 needs >= 3.11)
- jellyfish | https://jpt.sh/projects/jellyfish/ | soundex, metaphone, MRA | R10 | MIT | 1.2.1: 2025-10-11 | 1 | USE | no deps; pinned 1.2.1 (1.3.0 needs >= 3.11); MRA too lax as a sole match signal
- fhir.resources | https://github.com/nazrulworld/fhir.resources | pydantic FHIR models | R4 | BSD | 2026-07-03 | 2 | ADAPT (tests only) | no R4 package (R4B/STU3/R5); 9 ms per bundle; accepts a bad Bundle.type
- indic-transliteration | https://github.com/indic-transliteration/indic_transliteration_py | Devanagari<->IAST/ITRANS | R7,R10 | MIT | 2026-11-26 | 1 | BUILD instead | raw output keeps the schwa; pulls typer/tqdm/toml/roman; custom map is as good
- Faker | https://github.com/joke2k/faker | en_IN/hi_IN fake names | R22 tests | MIT | 2026-11-20 | 1 | USE (dev only) | mutation harness for unseen-format testing
- pytest | https://docs.pytest.org | tests | test | MIT | 2026-10-27 | 1 | USE | standard
- splink | https://github.com/moj-analytical-services/splink | Fellegi-Sunter + EM | R10 | MIT | 2026-09-28 | 5+ | REJECT | duckdb + pyarrow weight; rules are explainable in the viva
- presidio-analyzer | https://github.com/data-privacy-stack/presidio | PII NER framework | R5-R7 | MIT | 2026-10-27 | 10+ | REJECT | the PS warns off-the-shelf PII tools miss Hindi/Hinglish; NLP model setup (unverified)
- Screened out before shortlisting: recordlinkage 0.16 (last release 2023-07, stale), pycanon 1.3.7 (heavy pins), dateparser 1.5.1 (no round-trip), phonenumbers 9.0.44 (regex on the digit core is enough; optional later), pyahocorasick 2.3.1 (only if gazetteer scanning is slow).
## Already solved
- Format-correct skeleton (walk, decode, CSV/JSON round-trip, report/records writer, HMAC helper): kit starter/main.py. Copying it as a base is allowed; detection, linking and privacy must be ours.
- Contract and quality checks: kit validate_output.py, check_dev.py, check_submission.py. Don't rewrite them; wrap them in pytest/scripts.
- Primitives: HMAC (stdlib), AES-GCM (cryptography), Verhoeff (20-line table, 02-domain), JSON Pointer escaping (RFC 6901, 2 replaces).
## Datasets
- Kit dev set: ../Secret-Wards-ToolKit/dev. 200 files, 815 records, 48 patients, synthetic, kit LICENSE MIT. Only practice data allowed: SATISFIES the PS (synthetic only).
- Self-generated mutations (Faker en_IN/hi_IN names, renamed columns, new date formats) for the R22 unseen-format proxy. No external dataset needed or allowed.
## Integration notes (for the coding agent)
- psutil: peak = max over 50 ms samples of Process().memory_info().rss + sum(child.memory_info().rss for child in children(recursive=True)), catching NoSuchProcess. Sample in a daemon thread; never use peak_wset (Windows-only). Write it to report.resources.peak_rss_mb.
- cryptography: `from cryptography.hazmat.primitives.ciphers.aead import AESGCM`; key = AESGCM.generate_key(256) in memory only; nonce = os.urandom(12) per blob; store nonce||ciphertext. Data <= 2^31-1 bytes per call.
- rapidfuzz: `from rapidfuzz.distance import JaroWinkler, Levenshtein` (normalized_similarity). Use on transliterated Latin keys, never across scripts directly.
- jellyfish: metaphone/soundex as blocking keys only; match_rating_comparison matched 12/12 positives in the smoke, so it is too permissive to decide a link.
- fhir.resources: `from fhir.resources.R4B.bundle import Bundle; Bundle.model_validate_json(text)` in tests. Add our own checks: Bundle.type in the BundleType codes, every reference equals some entry.fullUrl, Composition first for documents.
- Faker: `Faker("hi_IN")` gives Devanagari names; Faker.seed(n) for reproducible fixtures.
- Python 3.10-3.12 (user decision 2026-11-26): no 3.11+-only stdlib (no tomllib, no ExceptionGroup/except*). Every pin publishes cp310 + cp312 wheels for win_amd64 and manylinux (PyPI-verified): psutil 7.2.2, cryptography 50.0.2, rapidfuzz 3.14.5, jellyfish 1.2.1, fhir.resources 8.3.0 (pydantic 2.14.4, pydantic-core 2.50.5, fhir-core 1.1.12), Faker 40.63.0, pytest 9.2.0. Runtime deps go in requirements.txt, test-only deps in requirements-dev.txt.
## Differentiation gap
- Existing PII tools (Presidio-class) are English NER: no Devanagari or Hinglish names, no meaning traps (Dr. vs relative, C/O complaint), no cross-record linkage, no QI defence.
- We can add within time: a run-time cross-script gazetteer (harvested from the input's own columns, then projected through custom transliteration); conflict-checked linkage with null on weak evidence; per-patient HMAC date shifts; k-anonymity on rare cells with a measured risk number; and a mutation harness that shows unseen-format robustness to the judges.
## Risks and blockers
- Evaluator Python version is UNKNOWN (kit: 3.10+, kit CI 3.12). Mitigated: code and pins target 3.10-3.12. Setup must be tested in clean 3.10 and 3.12 venvs before submitting (NOT RUN yet).
- No real FHIR R4 validator offline. fhir.resources R4B is a partial check, so FHIR validity rests on our own checks (risk to the 15% FHIR part of integrity).
- Custom transliteration was tested on 12 hand-made names only. Medial-schwa misses (Shabnam) will lower cross-script link recall; measure on dev with check_dev.
- No paid APIs or keys. All wheels are verified on PyPI for Windows + Linux. setup is about 1-2 min (pip of 4 small wheels).
## Resolved unknowns
- 02-domain gap, psutil: works for tree peak RSS on Windows; same API on Linux (Linux not smoke-tested: verify under WSL before /verify-commit).
- 02-domain gap, fhir.resources: offline, 9 ms per bundle, but R4B only and lax on value sets. Test-only.
- 02-domain gap, transliteration: custom map >= library on a hand sample. BUILD custom.
- 01-ps R4 acceptance says "fhir.resources parse + reference-resolution check". Propose "fhir.resources R4B parse + own value-set and reference-resolution check". NEEDS USER APPROVAL.
- CLOSED (user 2026-11-26): the official ABHA format isn't needed; detect it by digit shape + label context like other IDs.
- Evaluator Python: still UNKNOWN; handled by targeting 3.10-3.12 (user decision).
## Sources
- https://pypi.org/pypi/{psutil,cryptography,fhir.resources,indic-transliteration,rapidfuzz,jellyfish,regex,pytest,phonenumbers,splink,recordlinkage,pycanon,Faker,dateparser,presidio-analyzer,pyahocorasick,fhir-core}/json
- https://github.com/giampaolo/psutil · https://cryptography.io/en/latest/hazmat/primitives/aead/ · https://github.com/nazrulworld/fhir.resources · https://github.com/indic-transliteration/indic_transliteration_py
- https://github.com/rapidfuzz/RapidFuzz · https://jpt.sh/projects/jellyfish/ · https://github.com/joke2k/faker · https://docs.pytest.org · https://github.com/moj-analytical-services/splink · https://github.com/data-privacy-stack/presidio
