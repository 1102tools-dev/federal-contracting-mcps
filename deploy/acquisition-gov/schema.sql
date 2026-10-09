-- Acquisition.gov hosted edition: a snapshot of every resource the five tools
-- can return, written by scripts/load_acquisition_gov.py. The Worker only reads.
--
-- sources holds one row per fetched resource per snapshot. Parsed content
-- (docs and the tables keyed by doc) is stored once per content hash and parser
-- version and shared between snapshots. meta.current names the snapshot readers
-- use; the loader stages a new snapshot under meta.staging and moves
-- meta.current in one statement when it is complete. Offsets and lengths count
-- Unicode code points, as Python's str does. Every statement is idempotent; the
-- loader applies this file before each run.

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,       -- current, previous, staging: snapshot ids
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY,
  started_at TEXT NOT NULL,
  completed_at TEXT,          -- set when it became current
  stats TEXT                  -- JSON summary of the run that completed it
);

CREATE TABLE IF NOT EXISTS sources (
  snapshot INTEGER NOT NULL,
  key TEXT NOT NULL,          -- index, part:<n>, guidance:<resource>, pdf:<url>
  url TEXT NOT NULL,          -- URL a tool requests
  final_url TEXT,             -- after redirects; tools report this as source_url
  source_id TEXT,             -- model-part-/guidance- id of final_url
  retrieved_at TEXT NOT NULL, -- when it was fetched, as tools report retrieved_at
  content_sha256 TEXT,
  error TEXT,                 -- the error a live fetch raised, when it failed
  doc TEXT,                   -- docs.id of the parsed content
  PRIMARY KEY (snapshot, key)
);
CREATE INDEX IF NOT EXISTS sources_doc ON sources(doc);

CREATE TABLE IF NOT EXISTS docs (
  id TEXT PRIMARY KEY,        -- hash of parser version, kind, inputs and body
  kind TEXT NOT NULL,         -- index, html, guidance_pdf, pdf
  info TEXT NOT NULL          -- JSON: dates, parse outcome, page count, ...
);

-- Long texts, split into rows: text (whole document), sections (heading
-- section lines), lines (guidance PDF lines).
CREATE TABLE IF NOT EXISTS chunks (
  doc TEXT NOT NULL,
  stream TEXT NOT NULL,
  seq INTEGER NOT NULL,
  start INTEGER NOT NULL,
  length INTEGER NOT NULL,
  body TEXT NOT NULL,
  PRIMARY KEY (doc, stream, seq)
);

-- HTML headings (or guidance PDF lines): casefolded text and the span of
-- their section in the sections (or lines) stream.
CREATE TABLE IF NOT EXISTS headings (
  doc TEXT NOT NULL,
  idx INTEGER NOT NULL,
  key TEXT NOT NULL,
  start INTEGER NOT NULL,
  end INTEGER NOT NULL,
  PRIMARY KEY (doc, idx)
);
CREATE INDEX IF NOT EXISTS headings_key ON headings(doc, key);

-- Agency deviation PDF pages, as the package extracts them one page at a time.
CREATE TABLE IF NOT EXISTS pages (
  doc TEXT NOT NULL,
  page INTEGER NOT NULL,
  seq INTEGER NOT NULL,       -- long pages span several rows
  start INTEGER NOT NULL,     -- offset of the page in all pages joined by newlines
  length INTEGER NOT NULL,    -- the page's full length (on every row)
  failure TEXT,               -- exception name when extraction failed
  over_cap INTEGER NOT NULL DEFAULT 0,
  applicability TEXT,         -- JSON [[line start, line end], ...] of applicability lines
  body TEXT NOT NULL,
  PRIMARY KEY (doc, page, seq)
);

-- The RFO index: one row per part card and per agency deviation link.
CREATE TABLE IF NOT EXISTS index_parts (
  doc TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  part INTEGER NOT NULL,
  updated_date TEXT,
  deviations INTEGER NOT NULL,
  item TEXT NOT NULL,         -- the card as the package parses it, without agency_deviations
  PRIMARY KEY (doc, ordinal)
);

CREATE TABLE IF NOT EXISTS index_deviations (
  doc TEXT NOT NULL,
  seq INTEGER NOT NULL,       -- position in the index, all cards in order
  part INTEGER NOT NULL,
  agency TEXT NOT NULL,
  source_id TEXT NOT NULL,
  url TEXT NOT NULL,
  item TEXT NOT NULL,         -- the deviation as the package parses it
  PRIMARY KEY (doc, seq)
);
CREATE INDEX IF NOT EXISTS index_deviations_source ON index_deviations(doc, source_id);
CREATE INDEX IF NOT EXISTS index_deviations_part ON index_deviations(doc, part);
CREATE INDEX IF NOT EXISTS index_deviations_agency ON index_deviations(doc, agency);
