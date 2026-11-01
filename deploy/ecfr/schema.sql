-- A copy of the current eCFR for the hosted eCFR Worker (D1 database "ecfr").
-- Written by scripts/load_ecfr.py; read by deploy/ecfr/src/tools.ts.
-- Row writes cost money past the plan's allowance, so every table is keyed for
-- change-only refreshes: a row is rewritten only when its hash changes.

-- eCFR's titles.json, one row per title, exactly as eCFR sent it (key order
-- kept). Its up_to_date_as_of is the copy's date for that title: the Worker
-- answers from D1 only for that date and forwards every other date live.
CREATE TABLE IF NOT EXISTS titles (
  number INTEGER PRIMARY KEY,
  json TEXT NOT NULL,
  hash TEXT NOT NULL
);

-- Every node of every title's structure tree (title, subtitle, chapter,
-- subchapter, part, subpart, subject_group, section, appendix, hed1).
CREATE TABLE IF NOT EXISTS nodes (
  title INTEGER NOT NULL,
  -- Path below the title, one "type:identifier" step per level, '/' and '%'
  -- in identifiers written %2F and %25; hed1 (no identifier) is "hed1:#<n>"
  -- with n its position among its siblings. The title itself is ''.
  -- A node's descendants are one primary-key range: key > K || '/' AND key < K || '0'.
  key TEXT NOT NULL,
  type TEXT NOT NULL,          -- eCFR's structure type
  identifier TEXT,             -- eCFR's identifier (NULL for hed1)
  -- The structure node as eCFR sent it, key order kept, with "children"
  -- (when present) replaced by true at the same position.
  structure TEXT NOT NULL,
  children TEXT,               -- JSON list of child keys in eCFR's structure order; NULL for leaves
  -- Parsed text of the node's XML DIV (see PORT_PROGRESS.md "Content format");
  -- NULL for nodes with no DIV of their own (above parts, hed1) or when chunked.
  content TEXT,
  chunks INTEGER NOT NULL DEFAULT 0,  -- > 0: content is split over that many chunks rows
  meta TEXT,                   -- the DIV's hierarchy_metadata as parsed JSON, _SUBSTITUTE_DATE_ kept; NULL if none
  flags INTEGER NOT NULL DEFAULT 0,   -- see PORT_PROGRESS.md "Flags"
  hash TEXT NOT NULL,          -- covers structure, children, content, meta, flags
  PRIMARY KEY (title, key)
);
-- An ordinary rowid table, not WITHOUT ROWID: rows average ~2 KB, which a
-- WITHOUT ROWID b-tree spills to overflow pages. Measured on Title 48: 37 MB
-- instead of 58 MB, for one extra index write per row.
CREATE INDEX IF NOT EXISTS nodes_identifier ON nodes (title, identifier);

-- content longer than one D1 statement allows, in order.
CREATE TABLE IF NOT EXISTS chunks (
  title INTEGER NOT NULL,
  key TEXT NOT NULL,
  seq INTEGER NOT NULL,
  text TEXT NOT NULL,
  PRIMARY KEY (title, key, seq)
) WITHOUT ROWID;

-- Whole documents: agencies.json (as eCFR sent it), in pieces.
CREATE TABLE IF NOT EXISTS docs (
  name TEXT NOT NULL,
  seq INTEGER NOT NULL,
  text TEXT NOT NULL,
  PRIMARY KEY (name, seq)
) WITHOUT ROWID;

-- Loader state (last run, rows written, safety-net rotation, hashes).
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
