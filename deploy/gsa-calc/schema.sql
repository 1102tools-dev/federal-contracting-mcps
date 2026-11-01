-- A copy of GSA CALC+ ceiling rates for the hosted CALC+ Worker (D1 database
-- "gsa-calc"). Written by scripts/load_gsa_calc.py; read by
-- deploy/gsa-calc/src/emulator.ts, which answers the query strings the Python
-- server would send to GSA's API.
--
-- Row writes cost money past the plan's allowance (every index is one more
-- write per row), so refreshes are change-only: a record is rewritten only when
-- its hash changes, and only the indexes below exist.
--
-- Nights: GSA rebuilds one Elasticsearch index every night. The copy keeps the
-- current night and, during a refresh, the next one side by side. A records row
-- belongs to nights v_from <= N < v_to; the Worker reads N = meta 'current'.
-- A refresh adds changed and new records with v_from = N+1, closes replaced and
-- removed ones with v_to = N+1, then moves 'current' and 'version' in one
-- statement (so no answer mixes two nights), then deletes rows with v_to <= N+1.

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
-- Keys:
--   current    the night the Worker reads (integer, as text)
--   version    GSA's index name for that night, e.g. ceilingrates-2026-11-01_02-00-02.
--              Also the answer cache's version: it changes with every switch.
--   timestamp  that night's _source._timestamp (GSA sets one value per build);
--              the Worker writes it into every returned _source
--   staging    the night a refresh is writing (absent otherwise)
--   loaded_at  when the current night was switched in (UTC ISO)

CREATE TABLE IF NOT EXISTS records (
  rid INTEGER PRIMARY KEY,          -- rowid; sources.rid points here
  id INTEGER NOT NULL,              -- GSA's _id (= _source.id)
  v_from INTEGER NOT NULL,
  v_to INTEGER NOT NULL DEFAULT 9223372036854775807,
  labor_category TEXT,
  vendor_name TEXT,
  idv_piid TEXT,
  price REAL,                       -- current_price rounded to float32 (GSA's index type), as a double
  next_year_price REAL,             -- also float32-rounded
  education_level TEXT,             -- GSA's word, e.g. Bachelors
  min_years_experience INTEGER,
  worksite TEXT,                    -- e.g. Customer_Facility
  business_size TEXT,               -- S or O
  security_clearance INTEGER,       -- 1/0 from GSA's boolean; NULL when missing
  sin TEXT,                         -- ',' || GSA's comma list || ',' for whole-code matching
  hash TEXT NOT NULL                -- sha256 of the _source JSON without _timestamp
);
-- An ordinary rowid table, not WITHOUT ROWID, and narrow: full scans for
-- statistics read these columns only; the _source text lives in sources.
CREATE INDEX IF NOT EXISTS records_labor_category ON records (labor_category);
CREATE INDEX IF NOT EXISTS records_vendor_name ON records (vendor_name);
CREATE INDEX IF NOT EXISTS records_idv_piid ON records (idv_piid);

-- GSA's _source for each records row, as Python's json.dumps writes the parsed
-- object (GSA's key order kept), read only for the hits on the returned page.
CREATE TABLE IF NOT EXISTS sources (
  rid INTEGER PRIMARY KEY,
  json TEXT NOT NULL
);

-- Distinct values of the three fields GSA's keyword and suggest-contains search,
-- so substring matching scans thousands of short strings instead of every
-- record. A candidate list only: the Worker still applies the exact predicate
-- to records. A refresh adds new values before the switch and drops values no
-- night uses after it, so the list is never missing a current value.
CREATE TABLE IF NOT EXISTS terms (
  field TEXT NOT NULL,              -- labor_category, vendor_name or idv_piid
  value TEXT NOT NULL,
  folded TEXT NOT NULL,             -- value as GSA compares it case-insensitively (see PROBE_FINDINGS.md)
  PRIMARY KEY (field, value)
) WITHOUT ROWID;
