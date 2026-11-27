# REVIEW (hardcode-check) | range WORKTREE on 357b571 | 2026-11-27 | verdict WARN

id | file:line | check | snippet | why | root-cause fix | severity
H1 | wards/names.py build_protect_mask (ASHA branch), _LABEL_TRAILING_WORDS_RE, _NEXT_CAP_TOK_RE | G | `text[max(0, m.start() - 60) : ...]`, `{0,3}`, `{1,30}` | look-back window and word/letter bounds inline at the call site (MISTAKES "constants added at the call site") | named constants in wards/config.py, regexes built from them | WARN
H2 | wards/names.py _HYPHEN_DIGITS_RE | H | `^\d+-\d+-\d+$` | repeats the `\d+-\d+-\d+` fragment already inside _FAST_PROTECT_RE | name the fragment once and build both from it (or a named group) | WARN

Checked: no new word lists (vocab lock, allowlist and R22 guard tests unchanged, ratchet passes); no dependency change; evidence is a required argument of _process_text (no optional-default evidence); no swallowed exceptions; ASHA handling is a context rule (person label before it, or a capitalised non-stop token after it), not a dev word.
Not verified: Python 3.10/3.12; behaviour of the ASHA context rule on Devanagari labels.
