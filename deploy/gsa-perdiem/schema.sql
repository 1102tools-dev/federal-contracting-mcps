-- GSA Per Diem hosted edition: the gsa-perdiem-mcp package's bundled GSA
-- files (servers/gsa-perdiem-mcp/src/gsa_perdiem_mcp/data), loaded by
-- scripts/load_gsa_perdiem.py. Every statement is idempotent; the loader
-- applies this file before each load.
--
-- Data is stored in immutable parts named by a hash of their source file.
-- A load writes any missing parts in full, checks their row counts, and only
-- then points the single release row at them, so readers switch from one
-- complete release to the next in one statement and never see a partial one.
-- Parts of the previous release are kept until the next load.

-- The active release. Readers resolve parts through it on every query.
CREATE TABLE IF NOT EXISTS release (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  release TEXT NOT NULL,       -- hash of the manifest and every part
  manifest TEXT NOT NULL,      -- data/manifest.json as loaded
  parts TEXT NOT NULL,         -- {"fy2026": "<part>", ..., "places": "<part>"}
  previous_parts TEXT NOT NULL DEFAULT '{}',
  loaded_at TEXT NOT NULL
);

-- Every part written, complete or not. Loader bookkeeping only.
CREATE TABLE IF NOT EXISTS parts (
  part TEXT PRIMARY KEY,
  kind TEXT NOT NULL,          -- 'year' or 'places'
  source TEXT NOT NULL,        -- source file name
  expected_rows INTEGER NOT NULL,
  complete INTEGER NOT NULL DEFAULT 0
);

-- One row per bundled fiscal year: the year file without its ZIP table, plus
-- the source block results cite (about 40 KB of JSON; one row read per call).
CREATE TABLE IF NOT EXISTS years (
  part TEXT PRIMARY KEY,
  fiscal_year INTEGER NOT NULL,
  data TEXT NOT NULL
);

-- GSA ZIP file: the rate areas listed for each ZIP, in file order. entries is
-- a JSON list of destination ids, or state codes for the state's standard rate.
CREATE TABLE IF NOT EXISTS zips (
  part TEXT NOT NULL,
  zip TEXT NOT NULL,
  entries TEXT NOT NULL,
  PRIMARY KEY (part, zip)
) WITHOUT ROWID;

-- Census 2020 place, town, and county names (places.json.gz): 'ST|name' to
-- a JSON list of [county key, kind]. Used for county lookups and tie-breaks.
CREATE TABLE IF NOT EXISTS places (
  part TEXT NOT NULL,
  key TEXT NOT NULL,
  hits TEXT NOT NULL,
  PRIMARY KEY (part, key)
) WITHOUT ROWID;

-- Written by the Worker, never by the loader: the hourly budget and pacing
-- for the shared api.data.gov key behind live GSA API calls.
CREATE TABLE IF NOT EXISTS upstream_calls (
  minute INTEGER PRIMARY KEY,  -- Unix time / 60
  calls INTEGER NOT NULL,
  first_at REAL NOT NULL       -- Unix seconds of the minute's first call
);

CREATE TABLE IF NOT EXISTS upstream_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  next_start REAL NOT NULL,    -- Unix seconds: earliest start for the next call
  cooldown_until REAL NOT NULL -- Unix seconds: provider Retry-After cooldown
);

INSERT OR IGNORE INTO upstream_state (id, next_start, cooldown_until) VALUES (1, 0, 0);
