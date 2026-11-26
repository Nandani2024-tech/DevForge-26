# 02-domain: privacy firewall primer (user knows Python + regex; new to linkage, k-anon, HMAC/AES-GCM, transliteration, FHIR)
## 1. Concept map
- R2 -> BOMs, encoding fallback, deep JSON -> L1 encoding, 4 R2 · R3/R15 -> JSON Pointer locators -> L1, L2c, 4 R15 · R4 -> FHIR Bundle, fullUrl, references -> L1, L2d, 4 R4
- R5-R7, R9 -> ID formats, Verhoeff, phone numbering, transliteration, context rules -> L1, L2a, 4 R6/R7 · R8 -> preserve probes (doses, Dr.) -> 4 R8, sec 6
- R10 -> blocking, Fellegi-Sunter, clustering without transitive merges -> L1, L2e, 3, 4 R10 · R11/R17 -> HMAC vs hash, A6/A7 -> L1, L2b, 4 R11
- R12 -> per-patient date shift -> L2f · R13/R14 -> quasi-identifiers, k-anonymity, generalisation, suppression -> L1, L2g, 3 · R18 -> AES-GCM, nonces -> L1, 4 R18
## 2. Foundations
**L0 prerequisites**
- Bytes vs text: a file is bytes, and an encoding maps bytes to characters. The same bytes can decode differently, or fail to decode.
- Hash (SHA-256): a fixed 32-byte fingerprint of the input. Anyone can recompute it, so a hash of a phone number can be reversed by brute force over all phone numbers.
- Unicode scripts: Devanagari letters are U+0900-097F, and its digits ०-९ are U+0966-096F. NFKC normalises compatibility forms.
- A JSON document is a tree of objects, arrays and leaves. A record is one row or one subtree.
**L1 core concepts**
- BOM: a leading byte marker naming the encoding: EF BB BF = UTF-8, FF FE = UTF-16LE, FE FF = UTF-16BE. It is the cheapest reliable encoding signal, which is what R2 needs.
- cp1252: a Windows single-byte encoding. 0x93/0x94 decode to the curly quotes U+201C/U+201D, and 0x81 is undefined (decode error). It is the legacy export case.
- Direct identifier: names one person by itself (Aadhaar, phone, ABHA, MRN, full name). Quasi-identifier (QI): harmless alone, but identifying in combination (age, gender, village, PIN, dates, rare diagnosis). Sweeney: 87% of the US population is likely unique on {ZIP, gender, DOB}.
- Pseudonym: a stable stand-in ID. Keyed: computed with a secret, so only the key holder can recompute or link it (A6/A7).
- HMAC: a keyed hash, HMAC(K, m) = H((K⊕opad) ‖ H((K⊕ipad) ‖ m)) (RFC 2104 construction, unverified here). Without K, you can't test guesses.
- AES-GCM: authenticated encryption. Key 128/192/256 bit, 12-byte nonce, 16-byte tag. Reusing a nonce with the same key breaks the security of those messages.
- k-anonymity: every QI combination in the release is shared by at least k records. Tools: generalisation (a broader value) and suppression (`*`). Its weaknesses are homogeneity (all k share the same diagnosis) and background knowledge.
- Record linkage: deciding which records are the same person without a shared key. Blocking: only compare pairs that share a cheap key. Fellegi-Sunter: score each field's agreement or disagreement by m/u likelihood ratios.
- Transliteration: script-to-script mapping (Devanagari ↔ Latin). Indian names have many Latin spellings, so you compare in one normalised script.
- FHIR R4 Bundle: a JSON container of resources (`entry[].resource`), each with a `fullUrl`. References point to other entries.
**L2 mechanisms (worked examples)**
- a) Verhoeff check (Aadhaar's 12th digit, per NPCI via Wikipedia). Read the digits right to left as n_i, start c=0, then c = d[c][p[i mod 8][n_i]], and the number is valid iff c=0. Example 2363: (i0,n3,p=3,c=3), (i1,n6,p=3,c=1), (i2,n3,p=3,c=4), (i3,n2,p=1,c=0), so it is valid. Dev check: 54/68 Aadhaar-column values pass (79%), against about 10% for random digits. So it is a score boost, not a filter.
- b) HMAC pseudonym: ID = "PSN-" + base32(HMAC-SHA256(SECRET, canonical_cluster_key))[:k]. A different SECRET gives an unrelated ID (A7), and with no SECRET nothing can be inverted (A6). RFC 4231 TC2 checks the primitive.
- c) JSON Pointer (RFC 6901): to encode a key, first replace `~` with `~0`, then `/` with `~1`. To decode, replace `~1` first, then `~0`. Array indexes have no leading zeros. Key "a/b" gives "/a~1b", and the 4th visit gives "/visits/3".
- d) FHIR references: `urn:uuid:X` resolves to the entry whose fullUrl equals it. Dev: all 19 bundles are `type=document` with Composition first, and every fullUrl and reference is urn:uuid. If you change a fullUrl, rewrite every reference identically (or keep the uuids, which hold no PII).
- e) Fellegi-Sunter: say for surname m=0.95 and u=0.01 (assumed, illustrative). Agreement weight = log2(0.95/0.01) = log2(95) ≈ 6.57 and disagreement weight = log2(0.05/0.99) ≈ -4.31. Sum the weights over fields, then compare with an upper threshold (link), a lower threshold (no link), or the band between (here: null). Wikipedia does not state the log base; log2 is a convention.
- f) Per-patient date shift: shift = HMAC(SECRET, "shift|"+cluster) mod 2M − M, with 0 excluded. Admit 2026-03-28 and discharge 2026-04-06 (9 days), shifted +17: 2026-04-14 and 2026-04-23, still 9 days. Because each patient has a different shift, two known visit dates can't reveal one global offset (A5).
- g) Age band: lo = (age // 5) * 5, band = lo..lo+4. So 48 gives 45-49 and 50 gives 50-54, and the band always contains the age. A 97-year-old in a tiny village is still unique: coarsen that row (e.g. 90+, district only) or suppress it.
## 3. Our sub-problem
- Field: de-identification of free-text plus structured clinical data (HIPAA Safe Harbor style), combined with privacy-preserving record linkage and statistical disclosure control.
- Standard approaches: regex plus checksum for IDs; gazetteer plus context rules (labels, honorifics, relation markers) for names; CRF/NER (classical); Fellegi-Sunter or rule-based linkage (splink: F-S on DuckDB/Spark); k-anonymity via generalisation hierarchies and local suppression.
- Metrics: leak recall per type and script, precision on non-PII (here F2); pairwise P/R/F0.5 and B-cubed for linkage; re-identification risk = share of records with QI class size < k, or attacker success.
- Known failures: Latin-only gazetteers miss Devanagari; regex treats doses and lab values as phones; transitive closure merges homonyms; global date shift; unkeyed hash; over-redaction destroys utility.
## 4. Implementation notes (per R-id)
- R2: check the BOM, then strict UTF-8, then cp1252 strict; if all fail, quarantine `undecodable_text`. O(n). Detect JSON by content (`{`/`[` after whitespace) whatever the extension. For deep JSON, catch RecursionError (or parse iteratively) and quarantine; never raise the recursion limit to beat 1,500 levels (C stack risk).
- R3: keep the delimiter and quoting; csv module with newline="". Row count must be unchanged: suppression changes values, not rows (or use `out`). Write UTF-8 with LF.
- R4: walk resources and clean string leaves (name, telecom, address, identifier.value, text.div, attachment.data). Keep resourceType, id, fullUrl, references and codes. Re-encode base64 after cleaning. Validate with fhir.resources (unverified API) plus a reference-resolution check.
- R6: normalise Devanagari digits to ASCII first. Match on the digit core across separators. Phone: optional +91/91/0, then a first digit of 6-9, then 10 digits total. Aadhaar: 12 digits as 4-4-4 or 4-8 (dev shapes); Verhoeff raises confidence. ABHA: 14 digits, 2-4-4-4 (dev shape; official format unverified). PAN: `[A-Z]{5}\d{4}[A-Z]`, where the 4th char is the holder type (P = person). Lookarounds `(?<!\d)…(?!\d)`. Never match inside unit tokens (mg, mg/dL) or frequency patterns `\d-\d-\d`.
- R7: Pass A, label and column context (`Name:`, `नाम:`, header semantics); the value after a label is PII even if it is in no list (canaries). Pass B, relations S/o D/o W/o C/O, with `C/O` followed by a known complaint word kept. Pass C, honorific-adjacent tokens (ji, sahab, didi, श्री). Pass D, a gazetteer of names learned from the structured columns of the same input run (not dev lists), projected to both scripts by transliteration and then searched in free text. O(text × gazetteer) unless you use a trie or Aho-Corasick.
- R10: features per record are normalised names (both scripts → one Latin key, phonetic), strong IDs, phone, DOB, relative name, village, and age±1. Link on a strong ID unique to one person, or name plus one corroborating field (per DATASET.md). Cluster with union-find only on high-confidence edges, then reject any merge that puts two different strong IDs of the same type, or conflicting DOBs, into one cluster. Iterate in sorted order (determinism). Blocking keys: phonetic surname, phone, ID core.
- R11: the HMAC input is the cluster's canonical key = min(sorted member strong keys), not a record id, so the ID is stable across files. Write the ID in a patient_ref column, key or `Patient:` line, and in records.jsonl.
- R12: parse each date with the file's convention (day-first, month-first or ISO, from the column or the hospital), shift, then write back in the SAME format. If the cluster is unknown, use a per-record HMAC shift (still exact within the record).
- R14: compute equivalence classes on (age band, gender, district, admit week or month, rare diagnosis flag). If a class has fewer than k members (policy min_group_size = 5), widen the band, then drop the village, then suppress the rare value. Measure the share of records in small classes before and after.
- R15: `row:N` is 0-based, header excluded. Pointers use the RFC 6901 escape. `doc` is for text, FHIR and single objects. Counts come from what was actually written.
- R18: AESGCM(key from os.urandom, held in memory only). Use a fresh 12-byte nonce per blob via os.urandom (random nonces are fine for few messages). Encrypt any spill file in TMPDIR and delete it at exit. Never log values, only counts.
- R19: sorted() everywhere; no set iteration, time or random in the output path; json.dumps(sort_keys or a stable key order).
- R20: peak RSS via psutil (sum the process and its children: memory_info().rss sampled, or Linux ru_maxrss). On Windows, psutil's `peak_wset` (unverified). Stream large files.
## 5. Test oracles (hand-derived or from a source; none from dev/truth)
1. Verhoeff: "2363" -> valid; "2364" -> invalid; "9427" -> valid. Source: Wikipedia worked example (236→3, 942→7); 2364 differs in the check digit.
2. HMAC-SHA256(key=b"Jefe", msg=b"what do ya want for nothing?") -> 5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843. Source: RFC 4231 TC2; reproduced with Python.
3. JSON Pointer: key "a/b" -> "/a~1b"; key "m~n" -> "/m~0n"; decode "~01" -> "~1". Source: RFC 6901 secs 4-5.
4. Date shift +17: (2026-03-28, 2026-04-06) -> (2026-04-14, 2026-04-23), interval 9 = 9. Leap year: 2024-02-28 +2 -> 2024-03-01; 2026-02-28 +2 -> 2026-03-02. Derived by hand (March has 31 days) and checked with datetime.
5. Age band (w=5): 0->0-4, 4->0-4, 5->5-9, 48->45-49, 50->50-54, 97->95-99. Derived: lo = age//5*5.
6. Edge (01-ps sec 7): a zero-byte file -> status quarantined, output null, reason empty_file, input_sha256 = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 (the well-known SHA-256 of empty input; checked with hashlib). Decoding: b"\xff\xfeA\x00" -> "A"; b"\x93hi\x94" -> U+201C,"hi",U+201D (cp1252); b"\x81" -> cp1252 strict error -> quarantine. Phone regex: "+91-98765-43210" and "098765 43210" -> core 9876543210; "Dolo 650mg 1-1-1 x 5 days", "BP 117/82", "plt 1,45,000" -> no match (Python check).
## 6. Pitfalls
- Wrong: sha256(phone) as the pseudonym. Right: HMAC(SECRET, cluster key).
- Wrong: one global date offset. Right: a per-patient HMAC offset applied to all of that patient's dates.
- Wrong: union-find on every fuzzy name match. Right: high-confidence edges only, plus a conflict check; null when unsure.
- Wrong: requiring the Verhoeff checksum to flag Aadhaar. Right: a 12-digit shape in an ID context is enough (21% of dev values fail the checksum).
- Wrong: a name list copied from the practice data. Right: names harvested at run time from the input's own structured columns, plus context rules.
- Wrong: raising the recursion limit to parse a 1,500-deep JSON. Right: catch and quarantine (or an iterative parser).
- Wrong: reusing an AES-GCM nonce, or storing the key next to the data. Right: os.urandom nonce per message, key in memory only.
## 7. Explain it
- 30 s: Our firewall reads messy hospital files in three scripts and finds personal data by context, not by a fixed list. It links each patient across files with a keyed fake ID that nobody can reverse. It shifts each patient's dates by a secret amount, so stay lengths stay exact but visit dates can't be matched, and it widens or suppresses rare age-village-diagnosis combinations so a voter list can't single anyone out. Medical values come through byte-exact, and anything it can't parse is quarantined, never copied.
- 2 min: add the pipeline (ingest → evidence extraction → linkage → redaction → QI layer → export); why HMAC beats hashing (A6/A7); why per-patient shifts beat one global shift (A5); the k-anonymity check with measured risk; Fellegi-Sunter-style scoring with conflict checks to avoid homonym merges; encrypted spill files and count-only logs; and the numbers from check_dev.
## 8. Gaps and spec flags
- Resolved: the Aadhaar checksum does NOT reliably hold on the synthetic data (79% pass), so 01-ps R6 must not depend on it.
- Resolved: dev FHIR uses only urn:uuid references in document bundles, so R4 can keep the uuids and just clean leaves.
- Flag (not a requirement change): R20's "cross-platform peak RSS" needs psutil (an extra dependency) or a Linux-only ru_maxrss. Decide in /prior-art-scan.
- Unclear for /prior-art-scan: (1) the official ABHA number and address format (the ABDM pages render no text); (2) whether fhir.resources validates R4 offline and quickly enough; (3) indic-transliteration Devanagari→Latin quality for names (MIT; ITRANS/IAST schemes), compared with a simple custom mapping.
## 9. Self-test
1. Why decode with BOM first? A BOM unambiguously names UTF-8 or UTF-16, and sniffing without one can mistake UTF-16 for cp1252.
2. What makes a number Aadhaar-valid? 12 digits whose Verhoeff checksum gives c=0. Here it is only a hint.
3. Why HMAC and not SHA-256? Without the key, an attacker can't recompute IDs from known phones or Aadhaar numbers.
4. How does JSON Pointer encode the key "a/b"? As "/a~1b" (`~` is escaped first on encode, `~1` is decoded first).
5. What does a FHIR urn:uuid reference resolve to? The entry whose fullUrl equals it.
6. Why per-patient date shifts? A global shift is recovered from two known visits, while per-patient shifts keep intervals and hide the offset.
7. What does k-anonymity fail against? Homogeneity (one diagnosis in the class) and background knowledge, such as a rare disease with a known visit.
8. In our problem, when do we write patient null? When there is no strong ID unique to one person and no name plus corroborating field. A false merge costs more than a missed link.
## 10. Sources
- https://en.wikipedia.org/wiki/Verhoeff_algorithm (rev 1331921933) · https://www.rfc-editor.org/rfc/rfc4231 · https://www.rfc-editor.org/rfc/rfc6901
- https://hl7.org/fhir/R4/bundle.html · https://cryptography.io/en/latest/hazmat/primitives/aead/
- https://dataprivacylab.org/dataprivacy/projects/kanonymity/kanonymity.pdf (Sweeney 2002, IJUFKS 10(5):557-570) · https://en.wikipedia.org/wiki/K-anonymity
- https://en.wikipedia.org/wiki/Permanent_account_number · https://en.wikipedia.org/wiki/Telephone_numbers_in_India · https://en.wikipedia.org/wiki/Mobile_telephone_numbering_in_India (flagged outdated)
- https://en.wikipedia.org/wiki/Record_linkage (Fellegi & Sunter 1969, JASA 64(328):1183-1210, summary-derived) · https://github.com/indic-transliteration/indic_transliteration_py (MIT) · https://moj-analytical-services.github.io/splink/
- Kit: ../Secret-Wards-ToolKit/docs/{ATTACKS,DATASET,SCORING}.md. Local measurements: shape and checksum stats on dev/input (values not recorded).
