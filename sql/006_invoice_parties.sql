-- Supporting invoice observations are NOT settlement postings or verified facilities.
CREATE TABLE invoice_detail_runs (
 detail_id TEXT PRIMARY KEY,
 parse_id TEXT NOT NULL REFERENCES structured_runs(parse_id),
 parser_version TEXT NOT NULL,
 parser_sha256 TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(parse_id,parser_sha256)
);
CREATE TABLE invoice_page_candidates (
 invoice_page_id TEXT PRIMARY KEY,
 detail_id TEXT NOT NULL REFERENCES invoice_detail_runs(detail_id),
 page_number INTEGER NOT NULL,
 header_line_id TEXT REFERENCES source_line_candidates(line_id),
 order_raw TEXT,
 dispatch_raw TEXT,
 extraction_status TEXT NOT NULL CHECK(extraction_status IN ('party_blocks_unverified','unsupported_layout')),
 evidence_json TEXT NOT NULL,
 UNIQUE(detail_id,page_number)
);
CREATE TABLE invoice_party_candidates (
 party_id TEXT PRIMARY KEY,
 invoice_page_id TEXT NOT NULL REFERENCES invoice_page_candidates(invoice_page_id),
 role_candidate TEXT NOT NULL CHECK(role_candidate IN ('bill_to','shipper','receiver')),
 name_raw TEXT NOT NULL,
 address_block_raw TEXT NOT NULL,
 code_raw TEXT,
 evidence_json TEXT NOT NULL,
 review_status TEXT NOT NULL DEFAULT 'unverified' CHECK(review_status='unverified'),
 UNIQUE(invoice_page_id,role_candidate)
);
CREATE VIEW v_invoice_party_candidates AS
 WITH current AS MATERIALIZED (SELECT * FROM v_workbench_statements), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY parse_id ORDER BY created_at DESC,rowid DESC) n FROM invoice_detail_runs)
 SELECT s.original_filename,s.document_id,s.settlement_date,s.job_id,s.parse_id,p.page_number,
 p.order_raw,p.dispatch_raw,p.extraction_status,c.*
 FROM current s JOIN ranked r ON r.parse_id=s.parse_id AND r.n=1
 JOIN invoice_page_candidates p USING(detail_id) JOIN invoice_party_candidates c USING(invoice_page_id);
CREATE VIEW v_invoice_detail_coverage AS
 WITH current AS MATERIALIZED (SELECT * FROM v_workbench_statements), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY parse_id ORDER BY created_at DESC,rowid DESC) n FROM invoice_detail_runs)
 SELECT s.original_filename,s.document_id,s.parse_id,k.page_number,
 coalesce(p.extraction_status,'not_processed') AS extraction_status,
 (SELECT count(*) FROM invoice_party_candidates c WHERE c.invoice_page_id=p.invoice_page_id) AS party_blocks,
 'pending; invoice charges must not be added to owner settlement compensation' AS charge_detail_status
 FROM current s JOIN page_classifications k USING(parse_id)
 LEFT JOIN ranked r ON r.parse_id=s.parse_id AND r.n=1
 LEFT JOIN invoice_page_candidates p ON p.detail_id=r.detail_id AND p.page_number=k.page_number
 WHERE k.page_kind='freight_invoice';
