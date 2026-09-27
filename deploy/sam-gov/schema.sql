-- SAM.gov hosted edition: one row per active contract opportunity notice.
-- Loaded nightly by scripts/load_sam_opportunities.py from SAM.gov's public
-- ContractOpportunitiesFullCSV.csv, which lists every active notice. Notices
-- SAM.gov drops from that file are deleted here, so the table mirrors what is
-- active on SAM.gov as of the file date. The file also lists earlier versions
-- of amended notices; is_latest marks the newest version of each. Every
-- statement is idempotent; the loader applies this file before each load.

CREATE TABLE IF NOT EXISTS opportunities (
  rowid INTEGER PRIMARY KEY,
  notice_id TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  solicitation_number TEXT,
  department TEXT,
  cgac TEXT,
  sub_tier TEXT,
  fpds_code TEXT,
  office TEXT,
  aac_code TEXT,
  posted_at TEXT,            -- 'YYYY-MM-DD HH:MM:SS' as published
  posted_date TEXT,          -- 'YYYY-MM-DD'
  notice_type TEXT,          -- current type (Type column)
  base_type TEXT,            -- original type (BaseType column)
  archive_type TEXT,
  archive_date TEXT,         -- 'YYYY-MM-DD'
  set_aside_code TEXT,
  set_aside TEXT,
  response_deadline TEXT,    -- as published, with its UTC offset
  response_deadline_utc TEXT,-- 'YYYY-MM-DDTHH:MM:SSZ' for comparisons
  naics_code TEXT,
  psc_code TEXT,
  pop_street TEXT,
  pop_city TEXT,
  pop_state TEXT,
  pop_zip TEXT,
  pop_country TEXT,
  award_number TEXT,
  award_date TEXT,
  award_amount REAL,
  awardee TEXT,
  primary_contact_title TEXT,
  primary_contact_name TEXT,
  primary_contact_email TEXT,
  primary_contact_phone TEXT,
  primary_contact_fax TEXT,
  secondary_contact_title TEXT,
  secondary_contact_name TEXT,
  secondary_contact_email TEXT,
  secondary_contact_phone TEXT,
  secondary_contact_fax TEXT,
  organization_type TEXT,
  office_state TEXT,
  office_city TEXT,
  office_zip TEXT,
  office_country TEXT,
  additional_info_link TEXT,
  description TEXT,
  is_latest INTEGER NOT NULL DEFAULT 1, -- 0 when a newer version of this notice is listed
  row_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS opp_posted ON opportunities(posted_date);
CREATE INDEX IF NOT EXISTS opp_deadline ON opportunities(response_deadline_utc);
CREATE INDEX IF NOT EXISTS opp_type ON opportunities(notice_type);
CREATE INDEX IF NOT EXISTS opp_naics ON opportunities(naics_code);
CREATE INDEX IF NOT EXISTS opp_psc ON opportunities(psc_code);
CREATE INDEX IF NOT EXISTS opp_set_aside ON opportunities(set_aside_code);
CREATE INDEX IF NOT EXISTS opp_pop_state ON opportunities(pop_state);
CREATE INDEX IF NOT EXISTS opp_solicitation ON opportunities(solicitation_number COLLATE NOCASE);

-- Keyword search over titles and full descriptions.
CREATE VIRTUAL TABLE IF NOT EXISTS opportunities_fts USING fts5(
  title, description, content='opportunities', content_rowid='rowid', tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS opp_fts_insert AFTER INSERT ON opportunities BEGIN
  INSERT INTO opportunities_fts(rowid, title, description) VALUES (new.rowid, new.title, new.description);
END;
CREATE TRIGGER IF NOT EXISTS opp_fts_delete AFTER DELETE ON opportunities BEGIN
  INSERT INTO opportunities_fts(opportunities_fts, rowid, title, description) VALUES ('delete', old.rowid, old.title, old.description);
END;
CREATE TRIGGER IF NOT EXISTS opp_fts_update AFTER UPDATE ON opportunities BEGIN
  INSERT INTO opportunities_fts(opportunities_fts, rowid, title, description) VALUES ('delete', old.rowid, old.title, old.description);
  INSERT INTO opportunities_fts(rowid, title, description) VALUES (new.rowid, new.title, new.description);
END;

-- Load bookkeeping read by get_data_status.
CREATE TABLE IF NOT EXISTS load_status (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
