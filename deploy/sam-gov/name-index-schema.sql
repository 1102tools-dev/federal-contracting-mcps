-- sam-gov-name-index D1 only. Trigram name index for entity and exclusion
-- search. Kept out of sam-gov-entities because D1 cannot export a database
-- with virtual tables, and the public loader exports sam-gov-entities to
-- rehearse write costs. rowid = the source table's rowid in sam-gov-entities.
CREATE VIRTUAL TABLE IF NOT EXISTS entities_name_index USING fts5(legal, dba, tokenize='trigram', content='', contentless_delete=1, detail='none');
CREATE VIRTUAL TABLE IF NOT EXISTS exclusions_name_index USING fts5(name, full_name, short_name, tokenize='trigram', content='', contentless_delete=1, detail='none');
-- Fingerprint of the names each index row holds, so syncs rewrite only changes.
CREATE TABLE IF NOT EXISTS name_index_keys (kind TEXT NOT NULL, source_rowid INTEGER NOT NULL, names_hash TEXT NOT NULL, PRIMARY KEY(kind, source_rowid)) WITHOUT ROWID;
-- Written last, only after a complete sync. The Worker uses an index only when
-- this matches the extract_status snapshot its search read.
CREATE TABLE IF NOT EXISTS name_index_status (kind TEXT PRIMARY KEY CHECK(kind IN ('entities','exclusions')), source_sha TEXT NOT NULL, source_loaded_at TEXT NOT NULL, row_count INTEGER NOT NULL, synced_at TEXT NOT NULL);
