-- Append-only source-image transcriptions. These do not approve accounting treatment.
CREATE TABLE source_field_reviews (
 review_id TEXT PRIMARY KEY,
 job_id TEXT NOT NULL,
 page_number INTEGER NOT NULL,
 field_name TEXT NOT NULL CHECK(field_name IN ('settlement_date','gross_due')),
 raw_line TEXT NOT NULL,
 page_text_sha256 TEXT NOT NULL,
 value_json TEXT NOT NULL,
 evidence_json TEXT NOT NULL,
 reviewer TEXT NOT NULL,
 reason TEXT NOT NULL,
 created_at TEXT NOT NULL,
 FOREIGN KEY(job_id,page_number) REFERENCES source_pages(job_id,page_number)
);
CREATE INDEX reviews_by_job ON source_field_reviews(job_id,created_at);
CREATE TRIGGER source_reviews_no_update BEFORE UPDATE ON source_field_reviews
 BEGIN SELECT RAISE(ABORT,'Reviews are append-only; add a superseding review.'); END;
CREATE TRIGGER source_reviews_no_delete BEFORE DELETE ON source_field_reviews
 BEGIN SELECT RAISE(ABORT,'Reviews are append-only.'); END;
-- structured_runs.parser_sha256 is the effective parser+review signature when reviews
-- exist. Preserve the source-code digest and exact input IDs separately here.
CREATE TABLE structured_review_inputs (
 parse_id TEXT PRIMARY KEY REFERENCES structured_runs(parse_id),
 source_code_sha256 TEXT NOT NULL,
 review_sha256 TEXT NOT NULL,
 review_ids_json TEXT NOT NULL
);
