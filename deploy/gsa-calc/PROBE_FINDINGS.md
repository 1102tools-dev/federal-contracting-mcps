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

## Settled (Worker agent, 2026-11-01; implemented in src/rules.ts and src/emulator.ts)

**keyword: grams of 2-4 characters, per field.** Counted over the night-1 copy for every keyword probe without a
filter (61 distinct keywords, night-1 index or 0 hits). A keyword of n >= 2 characters needs all of its
min(4, n)-character grams (which hold the shorter ones) inside one field value; n = 1 matches nothing.

| rule | keywords matching GSA's count |
|---|---|
| max gram 4, per field | **61 of 61** |
| max gram 4, across the three fields | 56 |
| max gram 3, per field | 50 |
| max gram 3, across the three fields | 48 |

Where the rules part (GSA / max3 per field / max3 across / max4 per field / max4 across): "manager project"
129 / 405 / 428 / **129** / 131; " project manager " 3,318 / 3,501 / 3,695 / **3,318** / 3,406; "senior software
engineer" 304 / 357 / 366 / **304** / 304; "Help Desk Specialist" 1,130 / 1,317 / 1,317 / **1,130** / 1,130;
"Cybersecurity Analyst" 495 / 534 / 537 / **495** / 498; "Facilities Maintenance" 47 / 47 / 52 / **47** / 50;
"analyst" 54,925 / 55,179 / 55,198 / **54,925** / 54,925; "Program Manager" 10,375 / 10,376 / 10,378 / **10,375** /
10,376; "engineer:" 3 / 3 / 5 / **3** / 3; "engineer*" 32 / 34 / 57 / **32** / 32.
SQL: each field's matching values come from `terms` with `NOT EXISTS (SELECT 1 FROM json_each(?) g WHERE
instr(folded, g.value) = 0)`: the grams go in as one JSON array, so the check is exact in SQL and any keyword
length uses one bound parameter per field (3 in all), within D1's 100. No Worker-side second pass is needed.
On the Mac's SQLite a whole keyword search (count over 351,334 records) takes 49-61 ms; 48 grams 47 ms.

**suggest-contains: the same gram rule on its one field.** All 13 night-1 suggest probes match GSA's hits.total
(chief 656, qa 1,117, booz 1,879, adv 4,677, saic 2, "pact, inc" 51, 012 1,256, ...). Plain substring differs on
"&": substring 14,180, grams (none) 0 = GSA. With a filter GSA answers a plain search (emulated).

**sin: standard-tokenizer pieces, as GLOB.** `('#' || lower(sin) || '#') GLOB` `*[^0-9],CODE,[^0-9]*`, the
`[^0-9]` side dropped where the code starts (left) or ends (right) with a letter. The stored list holds only
digits, letters and commas on night 1. Counts equal GSA's for 541611, 54161, 54151S, 54151s, 541330ENG,
541620 and 541512 (0).

**Match-all hits carry _score.** With no keyword, search, filter or exclude, GSA also sorts by _score: each
hit has `_score` 1.0 and a trailing 1.0 in `sort` ([20.1, 1.0]); max_score stays null. Unreachable.

**sum_of_squares: exactly rounded is the best match, not an exact one.** The emulator's sums are exactly
rounded (BigInt, = math.fsum). On night 1 that equals GSA's sum_of_squares in 847 of 1,005 answers; the other 158
are all exactly one unit in the last place off (GSA Kahan-sums per shard, then Kahan-adds the 5 shard partials,
dropping each shard's compensation). Modeling shards does worse on the first pages of the pull's price slices
(186 answers): exact 169, Elasticsearch 7 routing (murmur3 of _id, 640 routing shards) 165 with per-shard exact
or Kahan-in-_id-order sums, 6.x routing (mod 5) 162. Kept exact; compare-emulator counts a 1-ulp sum_of_squares
as documented noise. wage_stats.sum matched everywhere.

**terminated_early.** 3 of 13 suggest answers carry `"terminated_early": true` (qa 1,117; 47QRAA and 47qraa,
10,000 gte); no pattern (chief 656, booz 1,879, adv 4,677 and "project manager" 10,000 gte don't). Not
emulated; the Python server never reads it.

**Terms counts past GSA's stated error bound.** Where GSA's doc_count_error_upper_bound > 0 its counts are
5-shard undercounts. On night 1 GSA never counts more than the copy, but in 28 answers (21 labor_category,
7 current_price) a count is up to 2 below the copy's beyond its stated bound (e.g. price slice 92.2346-94.6598,
"Web Designer": GSA 7, bound 5, copy 13, checked in SQL). Counted as GSA approximation.

**Other rules now emulated:** page_size 0 (no hits) and 501 answered; page 0, page * page_size > 10,000 and an
unknown ordering refused with an empty 406; several ordering pairs drop idv_piid; sort=desc alone sorts by
current_price descending; the same filter field twice keeps the last; min_years_experience:N exact; education
codes unknown to GSA ignored (a filter of only unknown codes is no filter); worksite:customer /
contractor applied, any other worksite value ignored; security_clearance only yes/no.

**compare-emulator, night 1, after these rules** (`pull` + `probes`, 1,015 answers keyed by query):
0 different; 103 identical; 25 GSA noise only (tie order, a tie group cut by the page edge, 1-ulp
sum_of_squares, terminated_early); 32 percentiles/histogram only; 845 GSA-approximate terms (each may also have
noise or measured differences); 10 from the previous night's index (skipped by the manifest's index).
Pull (848 pages incl. the nurse page): 45 identical, 14 noise only, 1 percentiles/histogram only, 788
GSA-approximate; hits equal up to ties on every page after the idv_piid rule (790 pages reorder within ties, 128
cut a tie group at the page edge). Percentiles differ in 1,743 aggregations (median gap $0.0077, max $4.27);
histograms in 864 answers.

## Long keywords (night 2, 2026-11-02; implemented in src/rules.ts tooManyGrams)
The night-2 case "validation: keyword 500 characters" (reachable: the Python server's cap is 500) got GSA's
empty 406; the copy had answered 200. Length probes (GitHub runs 41393708469 and 41394076155, temp branch
calc-length-probe, recordings in `.snapshot.nosync/rec-length1`, `rec-length2`):
- keyword=: 343 characters answered, 344 refused, both for "a" repeated and for real words ("project manager
  senior analyst ..."). 72-343 all answered; 344, 350, 400, 450, 499 refused.
- suggest-contains=labor_category:TERM: the same cutoff on the term (343 answered, 344 refused).
- search=labor_category:VALUE: 499 characters answered (exact match, no grams).
This is Elasticsearch's max_clause_count (1,024): n characters give 3n - 6 grams of 2-4 characters, repeats
included, per field (3 x 343 - 6 = 1,023; 3 x 344 - 6 = 1,026). Not a URI limit (a 574-character search query
string is answered). compare-emulator night 2 with these probes: 1,333 answers, 0 different.
