-- Source registry only. Financial and freight migrations follow the pilot.
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_id TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS system_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inventory_runs (
    run_id TEXT PRIMARY KEY,
    scanned_at TEXT NOT NULL,
    relative_directory TEXT NOT NULL,
    file_count INTEGER NOT NULL CHECK(file_count >= 0)
);
CREATE TABLE IF NOT EXISTS source_documents (
    document_id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE CHECK(length(sha256) = 64),
    original_filename TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
    mime_type TEXT NOT NULL DEFAULT 'application/pdf',
    page_count INTEGER CHECK(page_count > 0),
    document_kind TEXT,
    first_seen_at TEXT NOT NULL,
    extraction_status TEXT NOT NULL DEFAULT 'not_started',
    financial_review_status TEXT NOT NULL DEFAULT 'not_reviewed'
);
CREATE TABLE IF NOT EXISTS source_occurrences (
    occurrence_id INTEGER PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES source_documents(document_id),
    provider TEXT NOT NULL DEFAULT 'local',
    relative_path TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_run_id TEXT NOT NULL REFERENCES inventory_runs(run_id),
    UNIQUE(document_id,provider,relative_path)
);
CREATE VIEW IF NOT EXISTS v_source_inventory AS
SELECT o.relative_path,d.original_filename,d.sha256,d.size_bytes,d.page_count,
       d.extraction_status,d.financial_review_status,o.last_seen_run_id
FROM source_occurrences o JOIN source_documents d USING(document_id);
