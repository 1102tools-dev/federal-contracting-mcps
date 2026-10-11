-- Separate public entities/exclusions D1 only. No opportunities tables.
CREATE TABLE IF NOT EXISTS entities (entity_id TEXT PRIMARY KEY NOT NULL, uei TEXT, cage_code TEXT, legal_business_name TEXT, dba_name TEXT, registration_status TEXT, purpose_of_registration TEXT, registration_date TEXT, activation_date TEXT, expiration_date TEXT, last_update_date TEXT, uei_status TEXT, exclusion_status_flag TEXT, public_display_flag TEXT, address_line_1 TEXT, address_line_2 TEXT, city TEXT, state TEXT, zip_code TEXT, country TEXT, primary_naics TEXT, entity_structure TEXT, entity_url TEXT, naics_codes_json TEXT, business_type_codes_json TEXT, sba_business_type_codes_json TEXT, record_json TEXT);
CREATE TABLE IF NOT EXISTS entity_naics (entity_id TEXT NOT NULL, code TEXT NOT NULL, PRIMARY KEY(entity_id,code));
CREATE TABLE IF NOT EXISTS entity_business_types (entity_id TEXT NOT NULL, code TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('business','sba')), PRIMARY KEY(entity_id,code,kind));
CREATE INDEX IF NOT EXISTS entities_0 ON entities (uei);
CREATE INDEX IF NOT EXISTS entities_1 ON entities (cage_code);
CREATE INDEX IF NOT EXISTS entities_2 ON entities (legal_business_name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS entities_3 ON entities (state);
CREATE INDEX IF NOT EXISTS entities_4 ON entities (primary_naics);
CREATE INDEX IF NOT EXISTS entities_5 ON entities (registration_status);
CREATE INDEX IF NOT EXISTS entities_6 ON entities (expiration_date);
CREATE INDEX IF NOT EXISTS entities_7 ON entity_naics (code);
CREATE INDEX IF NOT EXISTS entities_8 ON entity_business_types (code,kind);
CREATE INDEX IF NOT EXISTS entities_status_name ON entities (registration_status, legal_business_name COLLATE NOCASE, uei, entity_id);
CREATE TABLE IF NOT EXISTS exclusions (exclusion_id TEXT PRIMARY KEY NOT NULL, uei TEXT, cage_code TEXT, name TEXT, first_name TEXT, middle_name TEXT, last_name TEXT, suffix TEXT, classification TEXT, exclusion_type TEXT, exclusion_program TEXT, excluding_agency_code TEXT, excluding_agency_name TEXT, record_status TEXT, activation_date TEXT, termination_date TEXT, creation_date TEXT, last_update_date TEXT, address_line_1 TEXT, address_line_2 TEXT, city TEXT, state TEXT, zip_code TEXT, country TEXT, description TEXT, record_json TEXT);
CREATE INDEX IF NOT EXISTS exclusions_0 ON exclusions (uei);
CREATE INDEX IF NOT EXISTS exclusions_1 ON exclusions (cage_code);
CREATE INDEX IF NOT EXISTS exclusions_2 ON exclusions (name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS exclusions_3 ON exclusions (state);
CREATE INDEX IF NOT EXISTS exclusions_4 ON exclusions (record_status);
CREATE INDEX IF NOT EXISTS exclusions_5 ON exclusions (activation_date);
CREATE TABLE IF NOT EXISTS extract_status (
kind TEXT PRIMARY KEY, file_name TEXT NOT NULL, file_date TEXT NOT NULL,
source_url TEXT NOT NULL, loaded_at TEXT NOT NULL, row_count INTEGER NOT NULL,
sha256 TEXT NOT NULL, database_bytes INTEGER NOT NULL, load_seconds REAL NOT NULL,
source_rows INTEGER NOT NULL DEFAULT 0, rejected_rows INTEGER NOT NULL DEFAULT 0, opted_out_rows INTEGER NOT NULL DEFAULT 0, duplicate_rows INTEGER NOT NULL DEFAULT 0);
