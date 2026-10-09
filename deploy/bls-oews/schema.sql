-- BLS OEWS hosted edition: the OEWS release bundled with bls-oews-mcp
-- (servers/bls-oews-mcp/src/bls_oews_mcp/data/), copied into D1 by
-- scripts/load_bls_oews.py. Each load writes the release under a new version
-- number, checks its row counts, then points active_release at it in one
-- statement and deletes older versions. The Worker reads only the active
-- version, so it never sees a half-loaded release. Every statement is
-- idempotent; the loader applies this file before each load.

-- One row per loaded release. manifest is the package's data/manifest.json;
-- footnotes maps BLS footnote codes to their text.
CREATE TABLE IF NOT EXISTS release (
  version INTEGER PRIMARY KEY,
  database_sha256 TEXT NOT NULL,
  manifest TEXT NOT NULL,
  footnotes TEXT NOT NULL,
  loaded_at TEXT NOT NULL
);

-- The version the Worker answers from (a single row, id 1).
CREATE TABLE IF NOT EXISTS active_release (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  version INTEGER NOT NULL
);

-- One row per OEWS estimate cell: key is the 25-character series ID without
-- its 2-digit datatype (prefix, area, industry, occupation), v01..v17 are the
-- published values for datatypes 01..17 as BLS prints them ("-" for
-- unreleased cells, NULL where BLS has no series), and f01..f17 their
-- footnote codes.
CREATE TABLE IF NOT EXISTS cell (
  version INTEGER NOT NULL,
  key TEXT NOT NULL,
  v01 TEXT, v02 TEXT, v03 TEXT, v04 TEXT, v05 TEXT, v06 TEXT, v07 TEXT, v08 TEXT, v09 TEXT,
  v10 TEXT, v11 TEXT, v12 TEXT, v13 TEXT, v14 TEXT, v15 TEXT, v16 TEXT, v17 TEXT,
  f01 TEXT, f02 TEXT, f03 TEXT, f04 TEXT, f05 TEXT, f06 TEXT, f07 TEXT, f08 TEXT, f09 TEXT,
  f10 TEXT, f11 TEXT, f12 TEXT, f13 TEXT, f14 TEXT, f15 TEXT, f16 TEXT, f17 TEXT,
  PRIMARY KEY (version, key)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS occupation (
  version INTEGER NOT NULL,
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  PRIMARY KEY (version, code)
) WITHOUT ROWID;

-- code is the 7-digit OEWS area code (0000000 national, NN00000 states,
-- 00NNNNN metros and nonmetro areas).
CREATE TABLE IF NOT EXISTS area (
  version INTEGER NOT NULL,
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  PRIMARY KEY (version, code)
) WITHOUT ROWID;
