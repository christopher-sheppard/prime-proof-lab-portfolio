-- OCR evidence only. All candidate values require later parsing and reconciliation.
CREATE TABLE IF NOT EXISTS page_extraction_jobs (
    job_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES source_documents(document_id),
    config_hash TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    page_count INTEGER CHECK(page_count > 0),
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL CHECK(status IN ('running','complete','incomplete','failed')),
    last_error TEXT,
    UNIQUE(document_id,config_hash)
);
CREATE TABLE IF NOT EXISTS source_pages (
    job_id TEXT NOT NULL REFERENCES page_extraction_jobs(job_id),
    page_number INTEGER NOT NULL CHECK(page_number > 0),
    status TEXT NOT NULL CHECK(status IN ('extracted')),
    width_pixels INTEGER NOT NULL CHECK(width_pixels > 0),
    height_pixels INTEGER NOT NULL CHECK(height_pixels > 0),
    native_text TEXT NOT NULL,
    ocr_text TEXT NOT NULL,
    layout_text TEXT NOT NULL,
    text_sha256 TEXT NOT NULL CHECK(length(text_sha256)=64),
    word_count INTEGER NOT NULL CHECK(word_count >= 0),
    mean_word_confidence REAL,
    low_confidence_word_count INTEGER NOT NULL CHECK(low_confidence_word_count >= 0),
    section_hints_json TEXT NOT NULL,
    extracted_at TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'unverified' CHECK(review_status IN ('unverified','reviewed')),
    PRIMARY KEY(job_id,page_number)
);
CREATE TABLE IF NOT EXISTS source_words (
    job_id TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    word_index INTEGER NOT NULL CHECK(word_index > 0),
    raw_text TEXT NOT NULL,
    left_px INTEGER NOT NULL CHECK(left_px >= 0),
    top_px INTEGER NOT NULL CHECK(top_px >= 0),
    width_px INTEGER NOT NULL CHECK(width_px >= 0),
    height_px INTEGER NOT NULL CHECK(height_px >= 0),
    confidence REAL NOT NULL CHECK(confidence BETWEEN -1 AND 100),
    block_number INTEGER NOT NULL,
    paragraph_number INTEGER NOT NULL,
    line_number INTEGER NOT NULL,
    PRIMARY KEY(job_id,page_number,word_index),
    FOREIGN KEY(job_id,page_number) REFERENCES source_pages(job_id,page_number) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS source_header_candidates (
    candidate_id INTEGER PRIMARY KEY,
    job_id TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    raw_value TEXT NOT NULL,
    candidate_value TEXT,
    evidence_line TEXT NOT NULL,
    review_state TEXT NOT NULL CHECK(review_state IN ('needs_review','unparsed')),
    FOREIGN KEY(job_id,page_number) REFERENCES source_pages(job_id,page_number) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS extraction_issues (
    issue_id INTEGER PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES page_extraction_jobs(job_id),
    page_number INTEGER NOT NULL CHECK(page_number >= 0),
    issue_kind TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'open' CHECK(review_status IN ('open','resolved')),
    UNIQUE(job_id,page_number,issue_kind,detail)
);
CREATE INDEX IF NOT EXISTS idx_page_job_document ON page_extraction_jobs(document_id,updated_at);
CREATE INDEX IF NOT EXISTS idx_header_candidate_job ON source_header_candidates(job_id,page_number);
CREATE VIEW IF NOT EXISTS v_latest_document_extraction AS
WITH current_docs AS (
    SELECT DISTINCT document_id FROM source_occurrences WHERE last_seen_run_id=(
        SELECT run_id FROM inventory_runs ORDER BY scanned_at DESC,rowid DESC LIMIT 1)
), ranked AS (
    SELECT j.*,row_number() OVER (PARTITION BY document_id ORDER BY updated_at DESC,started_at DESC,job_id) AS rn
    FROM page_extraction_jobs j
), page_counts AS (
    SELECT job_id,count(*) AS pages_extracted FROM source_pages GROUP BY job_id
), issues AS (
    SELECT job_id,count(*) AS open_issues FROM extraction_issues WHERE review_status='open' GROUP BY job_id
)
SELECT d.document_id,d.original_filename,d.page_count,d.financial_review_status,
       r.job_id,r.status AS job_status,r.last_error,r.settings_json,
       coalesce(p.pages_extracted,0) AS pages_extracted,coalesce(i.open_issues,0) AS open_issues
FROM source_documents d JOIN current_docs USING(document_id)
LEFT JOIN ranked r ON r.document_id=d.document_id AND r.rn=1
LEFT JOIN page_counts p ON p.job_id=r.job_id
LEFT JOIN issues i ON i.job_id=r.job_id;
CREATE VIEW IF NOT EXISTS v_extraction_review AS
SELECT d.original_filename,i.page_number,i.issue_kind,i.detail,i.review_status,i.job_id
FROM extraction_issues i JOIN page_extraction_jobs j USING(job_id)
JOIN source_documents d USING(document_id);
