# GSA CALC+ behavior, from the night-1 probes (2026-11-01)

Recording: GitHub run 41263303785 (`.snapshot.nosync/rec-night1/`), index
ceilingrates-2026-11-01_02-00-03, copy `.snapshot.nosync/calc-night1.sqlite` (351,334 records,
equal to GSA's priced count). 171 probes; **11 were answered by the previous night's index**
(the run started at 01:59 UTC): their `index` in the manifest is ceilingrates-2026-10-31_02-00-02.
Ignore those 11 here; they are re-recorded on night 2. Comparison: `scripts/compare-emulator.ts`.

Each rule below was checked against GSA's counts on this night. "Reachable" = the Python server can
send it; unreachable ones are still emulated where cheap, so raw probes compare cleanly.

## keyword (reachable: keyword_search, igce_benchmark, price_reasonableness_check)
**Not a substring match.** GSA indexes labor_category / vendor_name / idv_piid with an n-gram
tokenizer over the whole lowercased value (spaces and punctuation are ordinary characters) and
the keyword query requires **every n-gram of the lowercased keyword** to appear somewhere in the
field value (Elasticsearch match, operator AND). Order and position don't matter.
- Gram sizes: 2 and 3 fit everything seen (a 2-character keyword = substring; longer keywords =
  every trigram present). Max gram 5+ is ruled out ("cyber project" must satisfy "manager project").
  Check 3 vs 4 against all probes and choose the one that matches.
- Evidence, keyword "manager project" (GSA 129 records, 61 titles; substring finds 3): matches
  "Cyber Project Manager I" (it has "er ", "r p", " pr" from "cyber project" plus every gram of
  "manager" and "project"), "Task Order Project Manager", "Project Manager I, Cyber Programs",
  "Project Facilitator (Communications Manager Proj. Admin)"; does NOT match "Project Manager I",
  "Senior Project Manager", "Program / Project Manager 1", "Cybersecurity Project Manager" (no "r p").
- Evidence, "Cybersecurity Analyst" (GSA 495, substring 460): the 35 extra are titles holding every
  trigram, e.g. "Cybersecurity Identity and Access Management Analyst" ("identity and" gives
  "ty ", "y a", " an"), "Cybersecurity Risk and Vulnerability Analyst", "Cybersecurity/Security Analyst",
  "Cloud Cyber Security Analyst / Cybersecurity Engineer I".
- "Program Manager": GSA 10,375 vs substring 10,372 (the same rule should explain the 3).
- `*` is a literal character, not a wildcard: "**" → 8,612 (titles containing "**"), "*engineer" → 10,
  "engineer*" → 32. (The Python server's own regex treats `*` as a wildcard when it classifies titles;
  that's the Python side's business, the emulator just matches GSA.)
- A 1-character keyword ("e") matches nothing (no grams; GSA returns 0 hits).
- Leading/trailing spaces count as characters (" project manager " → 3,318); the Python server strips
  keywords, so that's unreachable.
- Per-field vs across fields: unverified. Test both against the probes and pick the one that matches
  (start with per-field: each field value must hold every gram on its own).
- Case: lowercase on both sides (ENGINEER = engineer = eNgInEeR, all identical).

## sin filter (reachable: every tool with `sin`, sin_analysis)
GSA's sin field is text analyzed by Elasticsearch's **standard tokenizer**, and the filter is an exact
match on one lowercased token. The standard tokenizer (Unicode word boundaries) does **not** split at
a comma between two digits, so "541620,561210FAC" is ONE token ("541620,561210fac") and that record
does not match 541620; "561210FAC,541690E,541620" splits into 561210fac / 541690e / 541620 and does.
Rule that reproduced all five probed codes exactly: split the sin string at commas except a comma with
a digit on both sides; lowercase; match the lowercased code against the pieces.
| code | GSA | this rule | whole code anywhere |
|---|---|---|---|
| 541611 | 29,133 | 29,133 | 65,496 |
| 54161 | 370 | 370 | 1,363 |
| 54151S / 54151s | 129,043 | 129,043 | 136,426 |
| 541330ENG | 30,879 | 30,879 | 39,289 |
| 541620 | 3,488 | 3,488 | 13,867 |
Note for James later (not a parity question): GSA's SIN filter misses many records that list the SIN
(541611: 29,133 of 65,496). Matching GSA keeps answers identical; fixing it would change them.

## Other filters
- min_years_experience:N = exact match (52,604 for 5). Unreachable (Python sends experience_range).
- education_level with an unknown code ("ba", "Bachelors") is ignored (all records). Unreachable.
- The same filter field twice (business_size:S then :O) → the last one wins (107,309 = O). Unreachable.
- worksite IS applied by GSA now: worksite:customer → 185,410 = Customer_Facility; with keyword=nurse
  115 instead of 167. Unreachable (Python rejects worksite). Map customer → Customer_Facility (and,
  by analogy, contractor → Contractor_Facility); leave other values unfiltered unless evidence appears.
- price_range, experience_range, education_level codes and pipes, business_size, security_clearance:
  identical to the emulator's current rules.

## Ordering and paging
- A single ordering pair works for every field in ORDERING_FIELDS, including idv_piid, next_year_price
  and business_size. Text sorts by code point (uppercase before lowercase, "(" before "*").
  min_years_experience sorts numerically. (Reachable: one pair only.)
- Several ordering pairs: GSA dropped idv_piid from the sort (sort array [price, vendor, category,
  experience, education] for our 6 pairs). Unreachable; emulate by dropping idv_piid when more than one
  pair is sent.
- `sort=desc` with no `ordering` → current_price descending. Unreachable.
- page_size=501 → GSA answers 200 (the emulator says 406). Unreachable; match GSA if simple.

## Statistics
- wage_stats.sum_of_squares (and sum when large) must be the exactly rounded sum (Python math.fsum,
  i.e. Shewchuk / Neumaier-exact): plain or Kahan summation is off in the last digit in ~180 answers.
- Percentiles and histograms differ only on large result sets (median gap $0.0077, max $116.64 on the
  whole-index call), as expected and accepted.

## suggest-contains
Plain suggest probes match. With an added filter GSA ignores the suggestion and answers a normal search
(244,025 = business_size S). Unreachable.
